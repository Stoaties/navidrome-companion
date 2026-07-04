# navidrome-companion

A tiny, self-hosted music server that runs happily on a **Raspberry Pi Zero 2W**
(or anything else with Docker). It wraps [**Navidrome**](https://www.navidrome.org/)
— a fast, lightweight, Subsonic-compatible music server — with a small web app
that lets you **fill and manage your library from the browser**: download tracks,
import playlists, manage users, and expose it publicly over HTTPS.

Navidrome does what it's great at — indexing and streaming your music to any
Subsonic client (web, iOS, Android, desktop). navidrome-companion adds the piece
Navidrome intentionally leaves out: **getting music *into* the library** and
configuring the box, all without touching a terminal.

> **Status:** works and self-hosted daily, but it's a personal/hobby project —
> expect rough edges. Issues and PRs welcome.

---

## Features

- 🎵 **Download from a web form** — paste any link that
  [yt-dlp](https://github.com/yt-dlp/yt-dlp) understands (YouTube, SoundCloud,
  Bandcamp, …). It's fetched, transcoded to MP3, thumbnail-embedded and tagged.
- 💚 **Import Spotify playlists / albums / tracks** — paste a public Spotify link
  and each track's audio is found on YouTube and downloaded (no Spotify login).
- 📋 **Import a whole track list** — paste a list of track links or
  `Artist - Title` lines (one per line) to import playlists of **any size** with
  **zero keys** — see [Spotify imports](#spotify-imports) for why this matters.
- 🏷️ **Clean metadata via [MusicBrainz](https://musicbrainz.org/)** — each
  download is looked up (keyless) to fill in the canonical track, artist and
  **album** name plus MusicBrainz IDs, so Navidrome groups albums correctly and
  can fetch artist art.
- ⏯️ **Live job queue** — downloads run one at a time with a live log; pause,
  resume or cancel any job from the dashboard.
- ⚙️ **Configure from the browser** — public domain with automatic HTTPS via
  [Caddy](https://caddyserver.com/), plus user management.
- 🔒 **Auth on everything** — the management app is fully gated and Navidrome has
  its own login. A default admin is seeded on first boot and forced to reset.
- 🖥️ **Optional e-ink status display** — a Waveshare 2.13" HAT shows local IP
  (with a QR to open the UI), free space, track count and CPU/temp, plus a Wi-Fi
  onboarding QR when offline. See [`eink/`](eink/).

## Architecture

Three containers behind one reverse proxy. Navidrome and the companion share the
music folder; Navidrome reads it, the companion writes to it.

```
                        ┌──────────────── Caddy ────────────────┐
   browser ──HTTP/S──▶  │   /            → companion (FastAPI)   │
                        │   /navidrome/* → navidrome             │
                        └───────────────────┬───────────────────┘
                                            │
             companion (FastAPI)            │        navidrome
        ┌─────────────────────────┐         │   ┌──────────────────┐
        │ Spotify embed reader     │         └──▶│ indexes + streams│
        │ yt-dlp download worker   │             │ the library      │
        │ MusicBrainz tagging      │──── writes ─┼──▶ shared /music │
        └─────────────────────────┘             └──────────────────┘
```

| Component | Role |
| --------- | ---- |
| [Navidrome](https://www.navidrome.org/) | Indexes and streams the library (the star of the show) |
| [Caddy](https://caddyserver.com/) | Reverse proxy + automatic HTTPS |
| companion (FastAPI) | Download/import jobs, tagging, auth, settings |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Audio acquisition |
| [MusicBrainz](https://musicbrainz.org/) | Canonical metadata + album grouping |

## Quick start

Requirements: a **64-bit** OS (Raspberry Pi OS 64-bit / DietPi / any Linux) with
Docker and the Docker Compose plugin.

```bash
git clone https://github.com/Stoaties/navidrome-companion.git
cd navidrome-companion
cp .env.example .env          # optionally change the default admin password
docker compose up -d --build
```

Then open **http://<host-ip>/** and sign in:

| Username | Password   |
| -------- | ---------- |
| `admin`  | `changeme` |

You're prompted to change the password immediately on first login.

- Management app: `http://<host-ip>/`
- Music library (Navidrome): `http://<host-ip>/navidrome/`

## Downloading music

On the dashboard, **Add music** takes any single link:

- A **Spotify** playlist / album / track link → resolved to a track list, then
  each track's audio is downloaded from YouTube (see below).
- Anything else yt-dlp supports (**YouTube, SoundCloud, Bandcamp**, …) →
  downloaded directly.

Everything is converted to MP3, tagged, and dropped into the shared music folder
where Navidrome picks it up on its next scan.

## Spotify imports

You **cannot** stream Spotify audio (it's DRM-protected) — instead the companion
reads a Spotify link's **track list** and finds each song's audio on YouTube,
matching by title, artist and duration. There are two ways to get the track list,
and it's worth understanding the trade-off:

### 1. Paste a Spotify link (no setup, capped at 100)

Paste a public playlist/album/track link. The list is read straight from
Spotify's **public embed page** — no API key, no login. This is the zero-effort
path, but Spotify's embed **only exposes the first 100 tracks** of a playlist.

> Why not just use the Spotify API? Because as of **February 2026** Spotify's
> Developer API [requires a Premium account](https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security)
> (and limits development-mode apps). This project is deliberately built to work
> **without a Spotify account of any kind**, so the API is not the default path.

### 2. Paste a full track list (no setup, no cap) — recommended for big playlists

Use **Import a track list** and paste the whole playlist, **one track per line**.
Lines can be Spotify track links, `spotify:track:…` URIs, or plain
`Artist - Title` text. Because individual tracks aren't subject to the embed's
100-track limit, this imports playlists of **any size** with no keys.

**Tip:** in the Spotify desktop or web app, open a playlist, select all tracks
(`Ctrl/Cmd+A`), copy (`Ctrl/Cmd+C`) and paste into the box — it copies *every*
track link, not just the first 100.

### Optional: Spotify API credentials

If you *do* have access to the Spotify API, you can paste a Client ID/Secret in
**Settings → Spotify** and playlist links will resolve in full (no 100 cap) via
the official API. This is optional and off by default.

### Notes

- Only **public** playlists/albums are readable (set yours to public first).
- Imports download **one track at a time** and can take a while over slow links;
  progress is live in the job log, and you can pause/cancel.
- Matching isn't perfect — the occasional track won't have a good YouTube match.
  Anything skipped is listed in the job's result summary.

## Going public with a domain & HTTPS

1. Point a DNS `A`/`AAAA` record at your server's public IP.
2. Forward ports **80** and **443** to the machine.
3. In **Settings → Public access**, enter the domain (and optionally a Let's
   Encrypt email) and **Save**.

The companion pushes the config to Caddy's admin API live — Caddy obtains and
renews the TLS certificate automatically. No restart needed.

## Configuration reference

| Setting                   | Where          | Notes                                     |
| ------------------------- | -------------- | ----------------------------------------- |
| Default admin user / pw   | `.env`         | First boot only, then managed in the UI   |
| `MUSIC_PATH`              | `.env`         | Where music is stored (point at a USB drive if you like) |
| Public domain / HTTPS     | Settings UI    | Rendered into Caddy live                  |
| Users                     | Settings UI    | Add/remove; new users must reset password |
| MusicBrainz tagging       | Settings UI    | On by default; toggle off for fastest imports |
| Spotify API keys          | Settings UI    | Optional; only needed to exceed 100 via API |

Persistent state lives in `./data` (SQLite config + Navidrome database) and the
music folder. Nothing sensitive is committed — see [`.gitignore`](.gitignore).

## Running on a Pi Zero 2W

512 MB RAM and a quad-core Cortex-A53 is enough for a personal library:

- Use a **64-bit** OS — Navidrome and the Python image are `arm64`.
- Downloads are **serialized** to keep one ffmpeg job from swamping the CPU.
- Store the music folder on **external USB** to spare the SD card.
- The first `--build` is the slow part (compiling wheels); later boots are fast.
- Downloads over Wi-Fi are network-bound, not CPU-bound — a big playlist can take
  a couple of hours. Jobs auto-resume after a reboot or dropout (already-fetched
  tracks are skipped).

## Security notes

- **Change the default password** immediately — it's static so first login is
  frictionless, which means it's public knowledge.
- Caddy's admin API is bound to the internal Docker network only.
- Expose only ports **80/443**. Navidrome and the companion are reached through
  Caddy, never directly.

## Development

The management app is a small FastAPI project under [`backend/`](backend/):

```
backend/app/
  main.py         # routes, auth, session
  db.py           # SQLite storage (users, settings, jobs)
  spotify.py      # reads track lists (public embed, or optional Web API)
  musicbrainz.py  # canonical metadata + album lookup (keyless)
  downloader.py   # job worker: yt-dlp download + tagging + list parsing
  caddy.py        # renders + pushes Caddy config via the admin API
  templates/      # Jinja2 UI
  static/         # CSS + job-polling JS
```

Run it locally without Docker:

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
# yt-dlp is called as a subprocess — install it too for local runs:
pip install yt-dlp
COMPANION_DATA_DIR=./data MUSIC_DIR=./music \
  uvicorn app.main:app --reload
```

## Roadmap / future ideas

Contributions toward any of these are very welcome:

- **Playlist re-sync** — remember an imported playlist and pull only newly added
  tracks on demand or on a schedule.
- **Create the playlist in Navidrome** — mirror an imported list as an actual
  Navidrome playlist, not just loose tracks.
- **Better matching** — AcoustID/Chromaprint fingerprinting and smarter
  title/artist normalization to cut the miss rate further.
- **Cover art** — pull album art from the MusicBrainz Cover Art Archive.
- **More sources** — resolve Deezer / Apple Music / Tidal links to a track list
  the same way (metadata only), then fetch audio via yt-dlp.
- **Completion notifications** — ntfy / webhook / email when a job finishes.
- **Per-user libraries & quotas** — scope downloads and storage per account.
- **Off-peak scheduling & bandwidth caps** — for slow or metered connections.
- **Prebuilt multi-arch images** — publish `arm64`/`amd64` images so there's no
  local build step on the Pi.
- **Backup / restore** — one-click export of config + user database.

Have an idea? Open an issue.

## Contributing

1. Fork and create a feature branch.
2. Keep it small and focused; match the existing style (standard library first,
   minimal dependencies — this has to run on a Pi Zero).
3. Open a PR describing the change and how you tested it.

## Acknowledgements

Built on the shoulders of excellent open-source projects:
[**Navidrome**](https://www.navidrome.org/) (the actual music server),
[yt-dlp](https://github.com/yt-dlp/yt-dlp),
[MusicBrainz](https://musicbrainz.org/),
[Caddy](https://caddyserver.com/) and [FastAPI](https://fastapi.tiangolo.com/).

## License

MIT — see [LICENSE](LICENSE).
