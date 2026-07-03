"""Background download jobs.

Two kinds of job:
  * ``url``     — a direct link (YouTube, SoundCloud, Bandcamp, ...) fetched with
                  yt-dlp and converted to a tagged MP3.
  * ``spotify`` — a Spotify playlist/album/track. The track list is read from
                  Spotify's public embed page (see spotify.py, no API/OAuth),
                  then each track's audio is found and downloaded from YouTube
                  with yt-dlp and tagged with mutagen.

Jobs are serialized through a single worker thread so a Pi Zero 2W is never
asked to run two ffmpeg jobs at once. Output lands in MUSIC_DIR, which Navidrome
watches and rescans automatically.
"""
import glob
import os
import queue
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import uuid
from urllib.parse import urlparse

from . import db, spotify

MUSIC_DIR = os.environ.get("MUSIC_DIR", "/music")

_work: "queue.Queue[str]" = queue.Queue()
_worker_started = False
_lock = threading.Lock()

# Running subprocesses, keyed by job id. Guarded by _lock. Each is started in
# its own session (process group) so we can signal the whole tree — yt-dlp
# spawns ffmpeg children that must also be paused/killed.
_procs: dict[str, subprocess.Popen] = {}
# Jobs the user asked to cancel, so the worker skips them (if still queued) and
# _process reports "cancelled" rather than "failed" when the process is killed.
_cancelled: set[str] = set()


# ------------------------------------------------------ process/signal utils ---
def _signal_job(job_id: str, sig: int) -> bool:
    """Send a signal to a running job's process group. Returns True if sent."""
    with _lock:
        proc = _procs.get(job_id)
    if proc is None or proc.poll() is not None:
        return False
    try:
        os.killpg(os.getpgid(proc.pid), sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _run(cmd: list[str], job_id: str, quiet: bool = False,
         log_cmd: bool = True) -> int:
    """Run a subprocess, streaming (or, if quiet, capturing) its output.

    In quiet mode the command's output is not written to the job log unless it
    fails — this keeps the log readable when downloading many tracks in a row.
    """
    if log_cmd:
        db.append_job_log(job_id, "$ " + " ".join(shlex.quote(c) for c in cmd) + "\n")
    proc = subprocess.Popen(
        cmd,
        cwd=MUSIC_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,  # never block waiting on interactive prompts
        text=True,
        bufsize=1,
        start_new_session=True,  # own process group for pause/cancel signals
    )
    with _lock:
        _procs[job_id] = proc
    tail: list[str] = []
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if quiet:
                tail.append(line)
                if len(tail) > 40:
                    del tail[:-40]
            else:
                db.append_job_log(job_id, line)
        proc.wait()
        # yt-dlp exits 101 when --max-downloads is reached: not an error for us.
        if quiet and proc.returncode not in (0, 101):
            db.append_job_log(job_id, "".join(tail[-15:]))
        return proc.returncode
    finally:
        with _lock:
            _procs.pop(job_id, None)


# ---------------------------------------------------------------- direct URL ---
# Bound every network operation so a stalled connection (common on flaky Wi-Fi)
# can't hang a download for minutes — abort and retry instead. This is the main
# lever for download throughput on a Pi Zero 2W.
_YT_ROBUST = [
    "--socket-timeout", "20",
    "--retries", "3",
    "--fragment-retries", "3",
    "--extractor-retries", "2",
]


def _yt_dlp_cmd(url: str) -> list[str]:
    return [
        "yt-dlp",
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--embed-metadata",
        "--embed-thumbnail",
        *_YT_ROBUST,
        "--no-playlist" if "list=" not in url else "--yes-playlist",
        "-o", "%(uploader)s/%(title)s.%(ext)s",
        url,
    ]


# ------------------------------------------------------------------- Spotify ---
def _sanitize(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip().strip(".")
    return name[:180] or "unknown"


def _tag_mp3(path: str, track: "spotify.Track", album: str) -> None:
    """Best-effort ID3 tagging so Navidrome shows clean artist/title/album."""
    try:
        from mutagen.easyid3 import EasyID3
        from mutagen.mp3 import MP3
        try:
            audio = EasyID3(path)
        except Exception:  # noqa: BLE001 - no ID3 header yet; create one
            mp3 = MP3(path)
            mp3.add_tags()
            mp3.save()
            audio = EasyID3(path)
        audio["title"] = track.title
        if track.artist:
            audio["artist"] = track.artist
        if album:
            audio["album"] = album
        audio.save()
    except Exception:  # noqa: BLE001 - yt-dlp already embedded basic metadata
        pass


def _yt_search_cmd(out_tmpl: str, query: str, dur_s: int) -> list[str]:
    base = [
        "yt-dlp", "-x", "--audio-format", "mp3", "--audio-quality", "0",
        "--no-playlist", "--embed-thumbnail", *_YT_ROBUST, "-o", out_tmpl,
    ]
    if dur_s > 0:
        # Prefer a hit whose length matches the Spotify track (avoids picking
        # remixes, live versions, "sped up" edits, hour-long loops, etc.).
        lo, hi = max(dur_s - 25, 0), dur_s + 25
        return base + [
            "--match-filter", f"duration>={lo} & duration<={hi}",
            "--max-downloads", "1", f"ytsearch3:{query}",
        ]
    return base + [f"ytsearch1:{query}"]


def _primary_artist(artist: str) -> str:
    """The main artist, dropping featured/collaborators (Spotify joins with ', ')."""
    return artist.split(",")[0].split("&")[0].split(" feat")[0].strip()


def _download_track(track: "spotify.Track", album: str, job_id: str,
                    seen: set) -> bool:
    """Find and download one track's audio from YouTube. Returns success.

    ``seen`` holds destination paths already used in this job so a genuine
    duplicate within a playlist is disambiguated instead of overwriting.
    """
    dest_dir = os.path.join(MUSIC_DIR, _sanitize(track.artist or "Unknown Artist"))
    base = os.path.join(dest_dir, _sanitize(track.title))
    dest = base + ".mp3"
    if dest not in seen and os.path.exists(dest):
        # Present from a previous run — skip so re-running a playlist is cheap.
        seen.add(dest)
        db.append_job_log(job_id, "   already downloaded; skipping\n")
        return True
    if dest in seen:
        # A different track with the same name in this same job — don't clobber.
        i = 2
        while f"{base} ({i}).mp3" in seen or os.path.exists(f"{base} ({i}).mp3"):
            i += 1
        dest = f"{base} ({i}).mp3"

    # Progressive search: most specific first, then looser, so niche tracks
    # (featured artists, odd punctuation) still get found instead of failing.
    dur_s = track.duration_ms // 1000
    primary = _primary_artist(track.artist)
    q_primary = f"{primary} {track.title}".strip()
    attempts = [(track.query, dur_s)]
    if q_primary and q_primary != track.query:
        attempts.append((q_primary, dur_s))
    attempts.append((q_primary or track.query, 0))
    attempts.append((track.title.strip(), 0))

    with tempfile.TemporaryDirectory() as tmp:
        out_tmpl = os.path.join(tmp, "%(id)s.%(ext)s")
        mp3 = None
        for query, dur in attempts:
            if not query:
                continue
            _run(_yt_search_cmd(out_tmpl, query, dur), job_id,
                 quiet=True, log_cmd=False)
            found = glob.glob(os.path.join(tmp, "*.mp3"))
            if found:
                mp3 = found[0]
                break
        if not mp3:
            return False

        os.makedirs(dest_dir, exist_ok=True)
        shutil.move(mp3, dest)
        seen.add(dest)
        _tag_mp3(dest, track, album)
        return True


def _process_spotify(job_id: str, url: str) -> bool:
    """Resolve a Spotify link and download each track. True if any succeeded."""
    db.append_job_log(job_id, "Reading Spotify link via public embed page...\n")
    resolved = spotify.resolve(url)
    album = resolved.name if resolved.kind == "album" else ""
    total = len(resolved.tracks)
    db.append_job_log(
        job_id, f"Found {resolved.kind} '{resolved.name}' — {total} track(s).\n")

    ok = 0
    seen: set = set()
    failed: list[str] = []
    for i, track in enumerate(resolved.tracks, 1):
        with _lock:
            if job_id in _cancelled:
                break
        db.append_job_log(job_id, f"[{i}/{total}] {track.artist} — {track.title}\n")
        try:
            if _download_track(track, album, job_id, seen):
                ok += 1
            else:
                failed.append(track.title)
                db.append_job_log(job_id, "   ! not found on YouTube; skipped\n")
        except Exception as exc:  # noqa: BLE001 - one bad track shouldn't abort
            failed.append(track.title)
            db.append_job_log(job_id, f"   ! error: {exc}\n")

    summary = f"{ok}/{total} downloaded"
    if failed:
        db.append_job_log(
            job_id, f"\nFinished: {summary}. {len(failed)} not found:\n  - "
            + "\n  - ".join(failed) + "\n")
        summary += " · missing: " + ", ".join(failed)
    else:
        db.append_job_log(job_id, f"\nFinished: {summary}.\n")
    db.set_job_result(job_id, summary[:250])
    return ok > 0


# --------------------------------------------------------------- job pipeline ---
def _process(job_id: str):
    job = db.get_job(job_id)
    if job is None:
        return
    # The job may have been cancelled while still sitting in the queue.
    with _lock:
        already_cancelled = job_id in _cancelled or job["status"] == "cancelled"
    if already_cancelled:
        with _lock:
            _cancelled.discard(job_id)
        db.set_job_status(job_id, "cancelled")
        return

    db.set_job_status(job_id, "running")
    try:
        if job["kind"] == "spotify":
            success = _process_spotify(job_id, job["target"])
        else:
            success = _run(_yt_dlp_cmd(job["target"]), job_id) == 0
    except Exception as exc:  # noqa: BLE001 - surface any failure to the log
        db.append_job_log(job_id, f"\n[error] {exc}\n")
        db.set_job_status(job_id, "failed")
        return

    # A killed process returns non-zero; report "cancelled" if that was intended.
    with _lock:
        was_cancelled = job_id in _cancelled
        _cancelled.discard(job_id)
    if was_cancelled:
        db.set_job_status(job_id, "cancelled")
    else:
        db.set_job_status(job_id, "done" if success else "failed")


def _worker():
    while True:
        job_id = _work.get()
        try:
            _process(job_id)
        finally:
            _work.task_done()


def _ensure_worker():
    global _worker_started
    with _lock:
        if not _worker_started:
            threading.Thread(target=_worker, daemon=True).start()
            _worker_started = True


def resume_interrupted():
    """Re-queue jobs left unfinished by a restart/crash.

    The work queue lives in memory, so a restart orphans any running/queued job
    (leaving it stuck as 'running'). Re-queue them on startup; already-downloaded
    tracks are skipped, so resuming a playlist is cheap.
    """
    _ensure_worker()
    for row in db.list_jobs(100):
        if row["status"] in ("running", "queued", "paused"):
            db.set_job_status(row["id"], "queued")
            db.append_job_log(row["id"], "\n[resumed after restart]\n")
            _work.put(row["id"])


def is_spotify_url(url: str) -> bool:
    """True for Spotify web links or spotify: URIs (resolved via the embed)."""
    url = url.strip().lower()
    return "spotify.com" in urlparse(url).netloc or url.startswith("spotify:")


def enqueue(kind: str | None, target: str) -> str:
    """Create and queue a job. Returns job id.

    ``kind`` may be 'url', 'spotify', or None to auto-detect from the link, so a
    Spotify link works no matter which entry point it came from.
    """
    _ensure_worker()
    os.makedirs(MUSIC_DIR, exist_ok=True)
    if kind is None:
        kind = "spotify" if is_spotify_url(target) else "url"
    job_id = uuid.uuid4().hex[:12]
    db.create_job(job_id, kind, target)
    _work.put(job_id)
    return job_id


# ------------------------------------------------------------------- controls ---
def cancel(job_id: str) -> bool:
    """Cancel a queued, running or paused job. False if already finished."""
    row = db.get_job(job_id)
    if row is None or row["status"] in ("done", "failed", "cancelled"):
        return False
    with _lock:
        _cancelled.add(job_id)
    # If paused, resume first so the signal is delivered promptly, then kill.
    _signal_job(job_id, signal.SIGCONT)
    running = _signal_job(job_id, signal.SIGKILL)
    if not running:
        # Still queued (no live process): mark cancelled now for immediate UI.
        db.set_job_status(job_id, "cancelled")
    return True


def pause(job_id: str) -> bool:
    """Suspend a running job (SIGSTOP the process group)."""
    if _job_status(job_id) != "running":
        return False
    if _signal_job(job_id, signal.SIGSTOP):
        db.set_job_status(job_id, "paused")
        return True
    return False


def resume(job_id: str) -> bool:
    """Resume a paused job (SIGCONT the process group)."""
    if _job_status(job_id) != "paused":
        return False
    if _signal_job(job_id, signal.SIGCONT):
        db.set_job_status(job_id, "running")
        return True
    return False


def _job_status(job_id: str) -> str | None:
    row = db.get_job(job_id)
    return row["status"] if row else None
