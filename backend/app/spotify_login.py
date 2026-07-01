"""One-time interactive Spotify user login for spotdl.

Spotify no longer allows app-only (Client Credentials) tokens to read playlist
tracks — the API returns 401/403 "Valid user authentication required". spotdl
works around this with --user-auth, which needs a real user login. This script
performs that login once and stores the spotipy token cache on the persistent
data volume, so background downloads can reuse and auto-refresh it.

Run once, interactively:

    docker compose exec -it companion python -m app.spotify_login

It prints a URL to open, you authorize in your browser, then paste back the
URL your browser was redirected to.
"""
import sys

from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyOAuth

from . import db
from .downloader import SPOTIPY_CACHE, spotdl_default_creds

# Must match spotdl's own --user-auth configuration so the cached token is
# accepted and refreshed by spotdl (see spotdl/utils/spotify.py).
REDIRECT_URI = "http://127.0.0.1:9900/"
SCOPE = "user-library-read,user-follow-read,playlist-read-private"


def main() -> int:
    # Prefer custom credentials only if the user set them (advanced: requires a
    # Spotify app created before Nov 2024, which still has playlist access).
    # Otherwise use spotdl's built-in app, which is grandfathered in and already
    # has the 127.0.0.1:9900 redirect registered — so nothing to configure.
    client_id = db.get_setting("spotify_client_id", "")
    client_secret = db.get_setting("spotify_client_secret", "")
    using_builtin = not (client_id and client_secret)
    if using_builtin:
        client_id, client_secret = spotdl_default_creds()
        print("Using spotdl's built-in Spotify app (no custom keys set).")

    oauth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        cache_handler=CacheFileHandler(SPOTIPY_CACHE),
        open_browser=False,
    )

    if not using_builtin:
        print("\nStep 1. In your Spotify app settings, add this exact Redirect")
        print("        URI (Dashboard -> app -> Settings -> Redirect URIs), save:")
        print(f"\n            {REDIRECT_URI}\n")
    print("Open this URL, log in and click Agree:\n")
    print(f"            {oauth.get_authorize_url()}\n")
    print("Your browser will then fail to load a page at 127.0.0.1:9900 —")
    print("that is expected. Copy the FULL address-bar URL and paste it below.\n")

    response = input("Paste the redirect URL here: ").strip()
    try:
        code = oauth.parse_response_code(response)
        oauth.get_access_token(code, check_cache=False)
    except Exception as exc:  # noqa: BLE001 - report any auth failure plainly
        print(f"\n[x] Login failed: {exc}")
        return 1

    if oauth.get_cached_token():
        db.set_setting("spotify_user_auth", "1")
        print(f"\n[ok] Logged in. Token cached at {SPOTIPY_CACHE}.")
        print("     Spotify playlist/album downloads will now work.")
        return 0
    print("\n[x] Could not obtain a token. Double-check the pasted URL.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
