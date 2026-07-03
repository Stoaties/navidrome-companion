# navidrome-companion

A tiny, self-hosted music server for a **Raspberry Pi Zero 2W** (or anything
else that runs Docker). It wraps [Navidrome](https://www.navidrome.org/) — a
lightweight Subsonic-compatible music server — with a web management app that
lets you:

- 🎵 **Download music from a web interface** — paste any URL (YouTube,
  SoundCloud, Bandcamp, …) and it's fetched, converted to MP3 and tagged via
  [yt-dlp](https://github.com/yt-dlp/yt-dlp).
- 💚 **Import public Spotify playlists / albums / tracks** — the track list is
  read from Spotify's public page (no API key or login) and each track's audio
  is fetched from YouTube via yt-dlp and tagged.
- ⚙️ **Configure everything from the browser** — public domain (with automatic
  HTTPS via [Caddy](https://caddyserver.com/)) and users.
- 🔒 **Authentication on every web interface** — the management app is fully
  gated, and Navidrome has its own login. A default admin account is seeded on
  first boot.
- 🖥️ **Optional e-ink status display** — a Waveshare 2.13" HAT shows the local
  IP (with a QR to open the web UI), free space, track count and CPU/temp, and
  a Wi-Fi onboarding QR when offline. See [`eink/`](eink/).

Navidrome serves the actual library and streaming; the companion app handles
acquisition and configuration.

```
                       ┌─────────── Caddy ───────────┐
   browser ──HTTPS──▶  │  /            → companion    │
                       │  /navidrome/* → navidrome    │
                       └──────────────┬──────────────┘
                          companion (FastAPI)  navidrome
                          embed reader + yt-dlp ─▶ shared /music volume
```

## Quick start

Requirements: a 64-bit OS (Raspberry Pi OS 64-bit / DietPi) with Docker and the
Docker Compose plugin installed.

```bash
git clone https://github.com/Stoaties/navidrome-companion.git
cd navidrome-companion
cp .env.example .env          # optionally change the default admin password
docker compose up -d --build
```

Then open **http://<pi-ip>/** and sign in with the default credentials:

| Username | Password   |
| -------- | ---------- |
| `admin`  | `changeme` |

You'll be prompted to change the password immediately on first login.

- Management app: `http://<pi-ip>/`
- Music library (Navidrome): `http://<pi-ip>/navidrome/`

## Going public with a domain & HTTPS

1. Point a DNS `A`/`AAAA` record at your server's public IP.
2. Forward ports **80** and **443** to the machine.
3. In the app go to **Settings → Public access**, enter the domain (and
   optionally a Let's Encrypt email), and **Save**.

The companion pushes the new config to Caddy's admin API live — Caddy obtains
and renews the TLS certificate automatically. No restart needed.

## Spotify imports

**No API keys, no login, no setup.** Paste a **public** Spotify playlist, album
or track link on the dashboard. The companion reads the track list straight from
Spotify's public page (the same data an embedded player shows), then finds and
downloads each track's audio from YouTube with yt-dlp, matching by title, artist
and duration, and tags the resulting MP3.

This deliberately avoids the Spotify Web API, which since November 2024 blocks
playlist-track reads for newly created apps and heavily rate-limits shared ones.

Notes:

- Only **public** playlists/albums are readable. If yours is private, set it to
  public in Spotify first (Playlist → … → Make public).
- Playlists download **one track at a time** and can take a while; progress is
  shown live in the job log, and you can pause/cancel from the dashboard.
- Matching is by title/artist/duration, so the occasional track may not match
  perfectly — the job log lists anything it skipped.

## Configuration reference

| Setting                | Where            | Notes                                   |
| ---------------------- | ---------------- | --------------------------------------- |
| Default admin user/pw  | `.env`           | First boot only, then managed in the UI |
| Public domain / HTTPS  | Settings UI      | Rendered into Caddy live                |
| Users                  | Settings UI      | Add/remove; new users must reset pw     |

Persistent state lives in `./data` (SQLite config + Navidrome database) and the
`music` Docker volume. Nothing sensitive is committed — see `.gitignore`.

## Running on a Pi Zero 2W

The Pi Zero 2W has 512 MB RAM and a quad-core ARM Cortex-A53, which is enough
for a personal library. Tips:

- Use a **64-bit** OS — Navidrome and the Python images are `arm64`.
- Downloads are **serialized** (one at a time) to avoid overwhelming the CPU.
- Give the SD card some breathing room, or store `music/` on external USB.
- First `--build` is the slow part (compiling Python wheels); subsequent boots
  are fast.

## Security notes

- **Change the default password** immediately — it's intentionally static so
  first login is frictionless, which means it's public knowledge.
- Caddy's admin API is bound to the internal Docker network only; it is not
  published to the host.
- Only expose ports 80/443 publicly. Navidrome and the companion are reached
  through Caddy.

## Development

The management app is a small FastAPI project under [`backend/`](backend/):

```
backend/app/
  main.py        # routes, auth, session
  db.py          # SQLite storage (users, settings, jobs)
  spotify.py     # reads track lists from Spotify's public embed page
  downloader.py  # job worker: yt-dlp download + mutagen tagging
  caddy.py       # renders + pushes Caddy config via the admin API
  templates/     # Jinja2 UI
  static/        # CSS + job-polling JS
```

Run it locally without Docker:

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
COMPANION_DATA_DIR=./data MUSIC_DIR=./music \
  uvicorn app.main:app --reload
```

## License

MIT — see [LICENSE](LICENSE).
