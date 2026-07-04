"""Canonicalize track metadata via MusicBrainz — free, no API key required.

Given a title + artist (from Spotify) and, ideally, the track duration, look up
the matching recording to get the canonical track title, artist credit and an
album it appeared on, plus MusicBrainz IDs that Navidrome uses to group releases
and fetch artist art. This mainly fills the *album* gap: Spotify's public embed
gives no per-track album for playlists, so without this playlist imports land in
Navidrome with no album grouping.

Best-effort only: any failure (network, rate limit, low confidence) returns None
and the caller keeps the original Spotify metadata. MusicBrainz asks callers to
stay under ~1 request/second and send a descriptive User-Agent; both are honored.
"""
import threading
import time
from dataclasses import dataclass

import httpx

_UA = ("navidrome-companion/1.0 "
       "(https://github.com/Stoaties/navidrome-companion)")
_BASE = "https://musicbrainz.org/ws/2"
_MIN_INTERVAL = 1.1          # seconds between requests (MusicBrainz policy)
_MIN_SCORE = 85              # 0-100 search confidence below which we don't trust it
_DUR_TOL_MS = 7000           # recording length must be within this of Spotify's

_lock = threading.Lock()
_last_request = 0.0


@dataclass
class Match:
    title: str
    artist: str
    album: str = ""
    recording_mbid: str = ""
    artist_mbid: str = ""
    release_mbid: str = ""


def _throttle() -> None:
    global _last_request
    with _lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()


def _artist_credit(credit: list) -> tuple[str, str]:
    """Reassemble the full artist string and the primary artist MBID."""
    name = "".join((c.get("name") or c.get("artist", {}).get("name") or "")
                   + (c.get("joinphrase") or "") for c in credit).strip()
    mbid = (credit[0].get("artist", {}).get("id", "") if credit else "")
    return name, mbid


def _best_recording(recordings: list, duration_ms: int) -> dict | None:
    """Pick the recording that best matches score and (if known) duration."""
    good = [r for r in recordings if (r.get("score") or 0) >= _MIN_SCORE]
    if not good:
        return None
    if duration_ms > 0:
        matched = [r for r in good
                   if r.get("length")
                   and abs(r["length"] - duration_ms) <= _DUR_TOL_MS]
        if matched:
            # Among duration matches, the highest search score wins.
            return max(matched, key=lambda r: r.get("score") or 0)
    return good[0]  # already ordered by score


def _pick_album(releases: list) -> tuple[str, str]:
    """Choose the earliest official *studio* album from a release list.

    Conservative on purpose: we only return an album when it is clearly a studio
    album (primary type Album, no secondary types like Compilation/Live/Remix and
    an official status). Tagging a track with a random bootleg/compilation name is
    worse than leaving the album blank, so in that case we return nothing.
    """
    studios = [
        rel for rel in (releases or [])
        if (rel.get("release-group") or {}).get("primary-type") == "Album"
        and not ((rel.get("release-group") or {}).get("secondary-types"))
        and rel.get("status") == "Official"
    ]
    if not studios:
        return "", ""
    # Earliest release is normally the original studio album, not a reissue.
    best = min(studios, key=lambda rel: rel.get("date") or "9999")
    return (best.get("title") or ""), (best.get("id") or "")


def _recording_releases(mbid: str, timeout: float) -> list | None:
    """All releases a recording appears on (search truncates this list)."""
    if not mbid:
        return None
    try:
        _throttle()
        resp = httpx.get(
            f"{_BASE}/recording/{mbid}",
            params={"inc": "releases+release-groups", "fmt": "json"},
            headers={"User-Agent": _UA}, timeout=timeout)
        resp.raise_for_status()
        return resp.json().get("releases") or []
    except (httpx.HTTPError, ValueError):
        return None


def lookup(title: str, artist: str, duration_ms: int = 0,
           timeout: float = 8.0) -> Match | None:
    """Return canonical metadata for a track, or None if not confidently found."""
    title = (title or "").strip()
    artist = (artist or "").strip()
    if not title:
        return None
    query = f'recording:"{title}"'
    if artist:
        query += f' AND artist:"{artist}"'
    try:
        _throttle()
        resp = httpx.get(
            f"{_BASE}/recording",
            params={"query": query, "fmt": "json", "limit": 8},
            headers={"User-Agent": _UA}, timeout=timeout)
        resp.raise_for_status()
        recordings = resp.json().get("recordings") or []
    except (httpx.HTTPError, ValueError):
        return None

    rec = _best_recording(recordings, duration_ms)
    if rec is None:
        return None
    art_name, art_mbid = _artist_credit(rec.get("artist-credit") or [])
    # The search result truncates each recording's release list; a direct lookup
    # returns them all, so we can find the canonical studio album more often.
    album, release_mbid = _pick_album(
        _recording_releases(rec.get("id", ""), timeout) or rec.get("releases"))
    return Match(
        title=(rec.get("title") or title).strip(),
        artist=art_name or artist,
        album=album,
        recording_mbid=rec.get("id", ""),
        artist_mbid=art_mbid,
        release_mbid=release_mbid,
    )
