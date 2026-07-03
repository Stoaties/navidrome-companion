"""SQLite-backed storage for users, settings and download jobs.

Uses only the stdlib sqlite3 module to stay light on the Pi Zero 2W.
Passwords are hashed with PBKDF2-HMAC-SHA256 (stdlib), no external crypto deps.
"""
import os
import sqlite3
import hashlib
import hmac
import secrets
import time
from contextlib import contextmanager

DATA_DIR = os.environ.get("COMPANION_DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "companion.db")

_PBKDF2_ROUNDS = 200_000


@contextmanager
def get_conn():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                pw_salt TEXT NOT NULL,
                pw_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                must_change_pw INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                target TEXT NOT NULL,
                status TEXT NOT NULL,
                log TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            """
        )


# ---------------------------------------------------------------- passwords ---
def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ROUNDS
    )
    return salt, dk.hex()


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    _, computed = hash_password(password, salt)
    return hmac.compare_digest(computed, expected_hash)


# ------------------------------------------------------------------- users ---
def create_user(username: str, password: str, is_admin: bool = False,
                must_change_pw: bool = False):
    salt, pw_hash = hash_password(password)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users (username, pw_salt, pw_hash, is_admin, "
            "must_change_pw, created_at) VALUES (?,?,?,?,?,?)",
            (username, salt, pw_hash, int(is_admin), int(must_change_pw),
             int(time.time())),
        )


def get_user(username: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
    return row


def list_users():
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, username, is_admin, created_at FROM users ORDER BY id"
        ).fetchall()


def count_users() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]


def set_password(username: str, password: str):
    salt, pw_hash = hash_password(password)
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET pw_salt=?, pw_hash=?, must_change_pw=0 "
            "WHERE username=?",
            (salt, pw_hash, username),
        )


def delete_user(username: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE username=?", (username,))


# ---------------------------------------------------------------- settings ---
def get_setting(key: str, default: str | None = None):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


# -------------------------------------------------------------------- jobs ---
def create_job(job_id: str, kind: str, target: str):
    now = int(time.time())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO jobs (id, kind, target, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?)",
            (job_id, kind, target, "queued", now, now),
        )


def append_job_log(job_id: str, text: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET log = log || ?, updated_at=? WHERE id=?",
            (text, int(time.time()), job_id),
        )


def set_job_status(job_id: str, status: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET status=?, updated_at=? WHERE id=?",
            (status, int(time.time()), job_id),
        )


def get_job(job_id: str):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def list_jobs(limit: int = 50):
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, kind, target, status, created_at, updated_at "
            "FROM jobs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()


def count_active_jobs() -> tuple[int, int]:
    """(running, queued) — work in progress. Paused jobs count as neither."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(status='running'),0) AS running, "
            "COALESCE(SUM(status='queued'),0) AS queued FROM jobs"
        ).fetchone()
    return int(row["running"]), int(row["queued"])
