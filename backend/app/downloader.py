"""Background download jobs: direct URLs (yt-dlp) and Spotify (spotdl).

Downloads are serialized through a single worker thread so a Pi Zero 2W is
never asked to run two ffmpeg/spotdl jobs at once. Output lands in MUSIC_DIR,
which Navidrome watches and rescans automatically.
"""
import os
import queue
import shlex
import signal
import subprocess
import threading
import uuid
from urllib.parse import urlparse, urlunparse

from . import db

MUSIC_DIR = os.environ.get("MUSIC_DIR", "/music")
# spotipy token cache for Spotify user-auth, kept on the persistent data volume
# so a one-time login (app.spotify_login) survives restarts and is reused by
# every download job.
SPOTIPY_CACHE = os.path.join(
    os.environ.get("COMPANION_DATA_DIR", "/data"), ".spotipy")

_work: "queue.Queue[str]" = queue.Queue()
_worker_started = False
_lock = threading.Lock()

# Running subprocesses, keyed by job id. Guarded by _lock. Each is started in
# its own session (process group) so we can signal the whole tree — spotdl and
# yt-dlp spawn ffmpeg children that must also be paused/killed.
_procs: dict[str, subprocess.Popen] = {}
# Jobs the user asked to cancel, so the worker skips them (if still queued) and
# _process reports "cancelled" rather than "failed" when the process is killed.
_cancelled: set[str] = set()


def _pgid(proc: subprocess.Popen) -> int:
    return os.getpgid(proc.pid)


def _signal_job(job_id: str, sig: int) -> bool:
    """Send a signal to a running job's process group. Returns True if sent."""
    with _lock:
        proc = _procs.get(job_id)
    if proc is None or proc.poll() is not None:
        return False
    try:
        os.killpg(_pgid(proc), sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _run(cmd: list[str], job_id: str) -> int:
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
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            db.append_job_log(job_id, line)
        proc.wait()
        return proc.returncode
    finally:
        with _lock:
            _procs.pop(job_id, None)


def _yt_dlp_cmd(url: str) -> list[str]:
    return [
        "yt-dlp",
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--embed-metadata",
        "--embed-thumbnail",
        "--no-playlist" if "list=" not in url else "--yes-playlist",
        "-o", "%(uploader)s/%(title)s.%(ext)s",
        url,
    ]


def _clean_spotify_url(url: str) -> str:
    """Drop query/fragment from open.spotify.com links.

    Spotify share links append context params like ``?trackId=`` or ``?si=``.
    spotdl matches URL types by naive substring ("track" in "trackId"), so a
    playlist link with ?trackId= gets misread as a track and spotipy rejects it
    ("Unexpected Spotify URL type"). The entity is fully identified by the path,
    so stripping the query makes share links Just Work.
    """
    parts = urlparse(url)
    if "spotify.com" in parts.netloc:
        return urlunparse((parts.scheme, parts.netloc, parts.path, "", "", ""))
    return url


def _spotdl_cmd(url: str) -> list[str]:
    cmd = [
        "spotdl", "download", _clean_spotify_url(url),
        "--output", "{artist}/{album}/{title}.{output-ext}",
    ]
    client_id = db.get_setting("spotify_client_id", "")
    client_secret = db.get_setting("spotify_client_secret", "")
    if client_id and client_secret:
        cmd += ["--client-id", client_id, "--client-secret", client_secret]
    # Reading playlist/album tracks now requires a Spotify user login. If a
    # cached user token exists (created by app.spotify_login), use it; spotdl
    # refreshes it non-interactively. Gate on the file, not just a setting, so
    # a job never triggers an interactive prompt when no login has been done.
    if os.path.exists(SPOTIPY_CACHE):
        cmd += ["--user-auth", "--headless", "--cache-path", SPOTIPY_CACHE]
    return cmd


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
            cmd = _spotdl_cmd(job["target"])
        else:
            cmd = _yt_dlp_cmd(job["target"])
        code = _run(cmd, job_id)
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
        db.set_job_status(job_id, "done" if code == 0 else "failed")


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


def is_spotify_url(url: str) -> bool:
    """True for Spotify web links or spotify: URIs (handled by spotdl)."""
    url = url.strip().lower()
    return "spotify.com" in urlparse(url).netloc or url.startswith("spotify:")


def enqueue(kind: str | None, target: str) -> str:
    """Create and queue a job. Returns job id.

    ``kind`` may be 'url' (yt-dlp), 'spotify' (spotdl), or None to auto-detect
    from the link. Auto-detection means a Spotify link works no matter which
    box it was pasted into — yt-dlp cannot handle Spotify URLs, so misrouting
    was the #1 way "download from Spotify" appeared to silently fail.
    """
    _ensure_worker()
    os.makedirs(MUSIC_DIR, exist_ok=True)
    if kind is None:
        kind = "spotify" if is_spotify_url(target) else "url"
    job_id = uuid.uuid4().hex[:12]
    db.create_job(job_id, kind, target)
    _work.put(job_id)
    return job_id


def cancel(job_id: str) -> bool:
    """Cancel a queued or running (or paused) job.

    Queued jobs are marked so the worker skips them when dequeued; running jobs
    have their process group killed. Returns False for jobs already finished.
    """
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
