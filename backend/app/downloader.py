"""Background download jobs: direct URLs (yt-dlp) and Spotify (spotdl).

Downloads are serialized through a single worker thread so a Pi Zero 2W is
never asked to run two ffmpeg/spotdl jobs at once. Output lands in MUSIC_DIR,
which Navidrome watches and rescans automatically.
"""
import os
import queue
import shlex
import subprocess
import threading
import uuid
from urllib.parse import urlparse, urlunparse

from . import db

MUSIC_DIR = os.environ.get("MUSIC_DIR", "/music")

_work: "queue.Queue[str]" = queue.Queue()
_worker_started = False
_lock = threading.Lock()


def _run(cmd: list[str], job_id: str) -> int:
    db.append_job_log(job_id, "$ " + " ".join(shlex.quote(c) for c in cmd) + "\n")
    proc = subprocess.Popen(
        cmd,
        cwd=MUSIC_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        db.append_job_log(job_id, line)
    proc.wait()
    return proc.returncode


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
    return cmd


def _process(job_id: str):
    job = db.get_job(job_id)
    if job is None:
        return
    db.set_job_status(job_id, "running")
    try:
        if job["kind"] == "spotify":
            cmd = _spotdl_cmd(job["target"])
        else:
            cmd = _yt_dlp_cmd(job["target"])
        code = _run(cmd, job_id)
        db.set_job_status(job_id, "done" if code == 0 else "failed")
    except Exception as exc:  # noqa: BLE001 - surface any failure to the log
        db.append_job_log(job_id, f"\n[error] {exc}\n")
        db.set_job_status(job_id, "failed")


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


def enqueue(kind: str, target: str) -> str:
    """Create a job (kind: 'url' or 'spotify') and queue it. Returns job id."""
    _ensure_worker()
    os.makedirs(MUSIC_DIR, exist_ok=True)
    job_id = uuid.uuid4().hex[:12]
    db.create_job(job_id, kind, target)
    _work.put(job_id)
    return job_id
