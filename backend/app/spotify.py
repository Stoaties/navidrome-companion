"""Read Spotify track lists into (title, artist, duration) tuples — two ways.

1. **Public embed page** (default, no setup): ``open.spotify.com/embed/<type>/<id>``
   renders the track list into a ``__NEXT_DATA__`` JSON blob that is publicly
   readable for public playlists/albums/tracks. No API key, no OAuth. Its one
   limitation is that Spotify caps the embedded ``trackList`` at **100 tracks**,
   so larger playlists come back truncated (``Resolved.truncated`` is set).

2. **Official Web API** (optional, unlocks large playlists): if the admin saves a
   Spotify ``client_id`` + ``client_secret`` in Settings, we use the
   client-credentials flow and page through the *entire* playlist/album — no 100
   cap. Reading a public playlist/album by id still works with app credentials
   (unlike the recommendation/audio-feature endpoints deprecated in Nov 2024).

Either way we only get metadata here; the audio is downloaded separately with
yt-dlp. Only *public* playlists/albums are exposed; private ones are not.
"""
import base64
import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from . import db

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"
_EMBED_CAP = 100  # Spotify truncates the embed trackList at 100 items.


class SpotifyError(Exception):
    pass


@dataclass
class Track:
    title: str
    artist: str
    duration_ms: int = 0

    @property
    def query(self) -> str:
        return f"{self.artist} {self.title}".strip()


@dataclass
class Resolved:
    name: str
    kind: str            # playlist | album | track
    tracks: list[Track]
    truncated: bool = False   # True if we know more tracks exist than we returned
    source: str = "embed"     # "embed" or "api" — where the list came from


def parse_url(url: str) -> tuple[str, str]:
    """Return ``(type, id)`` from a Spotify web URL or ``spotify:`` URI."""
    url = url.strip()
    if url.startswith("spotify:"):
        parts = url.split(":")
        if len(parts) >= 3 and parts[-2] in ("playlist", "album", "track"):
            return parts[-2], parts[-1]
        raise SpotifyError(f"Unrecognized Spotify URI: {url}")
    # Handles /playlist/<id>, /embed/playlist/<id>, /intl-xx/playlist/<id>, ...
    segments = urlparse(url).path.strip("/").split("/")
    for i, seg in enumerate(segments):
        if seg in ("playlist", "album", "track") and i + 1 < len(segments):
            # Ids may carry a ?si=... query; strip anything non-alphanumeric.
            return seg, re.split(r"[^A-Za-z0-9]", segments[i + 1])[0]
    raise SpotifyError(f"Could not find a playlist/album/track id in: {url}")


# ------------------------------------------------------------------ dispatch ---
def resolve(url: str, timeout: float = 20.0) -> Resolved:
    """Fetch and parse a Spotify link into a name + list of tracks.

    Uses the official API when credentials are configured (full track list),
    otherwise the public embed page (capped at 100 tracks).
    """
    kind, sid = parse_url(url)
    cid = (db.get_setting("spotify_client_id") or "").strip()
    secret = (db.get_setting("spotify_client_secret") or "").strip()
    if cid and secret:
        try:
            return _resolve_api(kind, sid, cid, secret, timeout)
        except SpotifyError:
            # Bad/expired credentials or a transient API error — fall back to the
            # keyless embed so small playlists keep working regardless.
            pass
    return _resolve_embed(kind, sid, timeout)


# -------------------------------------------------------------- embed reader ---
def _artist(subtitle: str | None, entity: dict) -> str:
    if subtitle:
        return subtitle.replace("\xa0", " ").strip()
    names = [a.get("name") for a in (entity.get("artists") or [])
             if isinstance(a, dict) and a.get("name")]
    return ", ".join(names)


def _resolve_embed(kind: str, sid: str, timeout: float) -> Resolved:
    embed = f"https://open.spotify.com/embed/{kind}/{sid}"
    try:
        resp = httpx.get(embed, headers={"User-Agent": _UA},
                         timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise SpotifyError(f"Could not fetch the Spotify page: {exc}") from exc

    match = _NEXT_DATA.search(resp.text)
    if not match:
        raise SpotifyError(
            "No track data on the Spotify page — is the link public?")
    try:
        entity = (json.loads(match.group(1))
                  ["props"]["pageProps"]["state"]["data"]["entity"])
    except (KeyError, ValueError) as exc:
        raise SpotifyError(f"Unexpected Spotify page format: {exc}") from exc

    name = entity.get("name") or entity.get("title") or kind
    tracks: list[Track] = []
    for item in (entity.get("trackList") or []):
        title = (item.get("title") or "").strip()
        if title:
            tracks.append(Track(title, _artist(item.get("subtitle"), item),
                                int(item.get("duration") or 0)))
    if not tracks:  # a single track: the entity itself
        title = (entity.get("title") or entity.get("name") or "").strip()
        if title:
            tracks.append(Track(title, _artist(entity.get("subtitle"), entity),
                                int(entity.get("duration") or 0)))
    if not tracks:
        raise SpotifyError("No tracks found for this Spotify link.")
    # The embed caps at 100; if we hit that we almost certainly lost tracks.
    truncated = kind == "playlist" and len(tracks) >= _EMBED_CAP
    return Resolved(name=name, kind=kind, tracks=tracks, truncated=truncated,
                    source="embed")


# ---------------------------------------------------------------- Web API ---
_TOKEN_URL = "https://accounts.spotify.com/api/token"
_API = "https://api.spotify.com/v1"


def _api_token(client: httpx.Client, cid: str, secret: str) -> str:
    basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    try:
        r = client.post(_TOKEN_URL, data={"grant_type": "client_credentials"},
                        headers={"Authorization": f"Basic {basic}"})
        r.raise_for_status()
        return r.json()["access_token"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise SpotifyError(f"Spotify credentials rejected: {exc}") from exc


def _api_get(client: httpx.Client, url: str, token: str) -> dict:
    r = client.get(url, headers={"Authorization": f"Bearer {token}"})
    if r.status_code >= 400:
        raise SpotifyError(f"Spotify API {r.status_code} for {url}")
    return r.json()


def _api_track(item: dict) -> Track | None:
    """Build a Track from a Spotify API track object (playlist item or album)."""
    t = item.get("track", item)  # playlist items wrap the track under "track"
    if not t or not t.get("name"):
        return None
    artists = ", ".join(a.get("name", "") for a in (t.get("artists") or [])
                        if a.get("name"))
    return Track(t["name"].strip(), artists.strip(),
                 int(t.get("duration_ms") or 0))


def _api_paginate(client: httpx.Client, url: str, token: str) -> list[Track]:
    """Follow ``next`` links, collecting tracks from every page."""
    tracks: list[Track] = []
    while url:
        page = _api_get(client, url, token)
        for item in page.get("items", []):
            tr = _api_track(item)
            if tr:
                tracks.append(tr)
        url = page.get("next")
    return tracks


def _resolve_api(kind: str, sid: str, cid: str, secret: str,
                 timeout: float) -> Resolved:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        token = _api_token(client, cid, secret)
        if kind == "playlist":
            head = _api_get(client, f"{_API}/playlists/{sid}"
                            "?fields=name,tracks.total", token)
            name = head.get("name") or "playlist"
            tracks = _api_paginate(
                client,
                f"{_API}/playlists/{sid}/tracks?limit=100"
                "&fields=items(track(name,duration_ms,artists(name))),next",
                token)
        elif kind == "album":
            head = _api_get(client, f"{_API}/albums/{sid}", token)
            name = head.get("name") or "album"
            tracks = _api_paginate(
                client, f"{_API}/albums/{sid}/tracks?limit=50", token)
        else:  # single track
            t = _api_get(client, f"{_API}/tracks/{sid}", token)
            name = t.get("name") or "track"
            tr = _api_track(t)
            tracks = [tr] if tr else []
    if not tracks:
        raise SpotifyError("No tracks found for this Spotify link.")
    return Resolved(name=name, kind=kind, tracks=tracks, truncated=False,
                    source="api")
