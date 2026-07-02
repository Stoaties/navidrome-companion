"""Read Spotify track lists from the public embed page — no API key, no OAuth.

Spotify's embed pages (``open.spotify.com/embed/<type>/<id>``) render the track
list into a ``__NEXT_DATA__`` JSON blob that is publicly readable for public
playlists, albums and tracks. We parse that to get titles and artists, then
download the audio separately with yt-dlp. This sidesteps the Spotify Web API
entirely — which since Nov 2024 blocks playlist reads for newly created apps and
rate-limits shared ones.

Only *public* playlists/albums are exposed this way; private ones are not.
"""
import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"


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
            return seg, segments[i + 1]
    raise SpotifyError(f"Could not find a playlist/album/track id in: {url}")


def _artist(subtitle: str | None, entity: dict) -> str:
    if subtitle:
        return subtitle.replace("\xa0", " ").strip()
    names = [a.get("name") for a in (entity.get("artists") or [])
             if isinstance(a, dict) and a.get("name")]
    return ", ".join(names)


def resolve(url: str, timeout: float = 20.0) -> Resolved:
    """Fetch and parse a Spotify link into a name + list of tracks."""
    kind, sid = parse_url(url)
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
    return Resolved(name=name, kind=kind, tracks=tracks)
