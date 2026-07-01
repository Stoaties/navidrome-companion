"""Render and push Caddy configuration live via its admin API.

When the admin sets a public domain in Settings, we render a Caddyfile and POST
it to Caddy's /load endpoint. With a domain Caddy provisions HTTPS automatically
via Let's Encrypt; without one it falls back to plain HTTP on :80.
"""
import os

import httpx

from . import db

CADDY_ADMIN = os.environ.get("CADDY_ADMIN", "http://caddy:2019")


def render_caddyfile() -> str:
    domain = (db.get_setting("public_domain", "") or "").strip()
    site = domain if domain else ":80"
    tls = ""
    email = (db.get_setting("acme_email", "") or "").strip()
    if domain and email:
        tls = f"\ttls {email}\n"
    return (
        "{\n\tadmin 0.0.0.0:2019\n}\n\n"
        f"{site} {{\n"
        f"{tls}"
        "\thandle_path /navidrome/* {\n"
        "\t\treverse_proxy navidrome:4533\n"
        "\t}\n"
        "\treverse_proxy companion:8000\n"
        "}\n"
    )


def push_config() -> tuple[bool, str]:
    """Render current settings and load them into Caddy. Returns (ok, message)."""
    caddyfile = render_caddyfile()
    try:
        resp = httpx.post(
            f"{CADDY_ADMIN}/load",
            content=caddyfile.encode(),
            headers={"Content-Type": "text/caddyfile"},
            timeout=15.0,
        )
        if resp.status_code == 200:
            return True, "Caddy configuration reloaded."
        return False, f"Caddy rejected config ({resp.status_code}): {resp.text}"
    except httpx.HTTPError as exc:
        return False, f"Could not reach Caddy admin API: {exc}"
