# Contributing to navidrome-companion

Thanks for your interest! This is a small, self-hosted hobby project that wraps
[Navidrome](https://www.navidrome.org/) with a browser-based way to fill and
manage a music library. Contributions — bug reports, docs, and code — are very
welcome.

## Ways to help

- **Report a bug** or **request a feature** via the
  [issue tracker](https://github.com/Stoaties/navidrome-companion/issues).
- **Improve the docs** — even fixing a typo is a valid PR.
- **Pick up a roadmap item** — see the "Roadmap / future ideas" section in the
  [README](README.md#roadmap--future-ideas).

## Guiding principles

This project targets a **Raspberry Pi Zero 2W** (512 MB RAM, `arm64`). Please
keep changes in that spirit:

- **Standard library first.** Reach for a new dependency only when it clearly
  earns its place — every dependency is weight on a tiny board.
- **Keep it simple.** Small, focused modules over clever abstractions.
- **Fail gracefully.** Downloads run over flaky home Wi-Fi; network calls should
  time out and degrade rather than hang.
- **Match the surrounding style** — comment density, naming, and idioms.

## Development setup

The management app is a small [FastAPI](https://fastapi.tiangolo.com/) project
under [`backend/`](backend/). Run it locally without Docker:

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pip install yt-dlp          # called as a subprocess; needed for local runs
COMPANION_DATA_DIR=./data MUSIC_DIR=./music \
  uvicorn app.main:app --reload
```

Or run the whole stack the way it's deployed:

```bash
cp .env.example .env
docker compose up --build
```

### Project layout

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
eink/             # optional Waveshare 2.13" e-ink status display
```

## Testing your change

There's no heavy test harness — keep changes verifiable by hand:

- `python -m py_compile app/*.py` to catch syntax errors.
- Exercise the affected flow in the running app (download a track, import a
  list, change a setting) and confirm the job log / UI behaves.
- If you touch download matching or metadata, note in the PR what you tried it
  against (a few real tracks is enough).

## Submitting a pull request

1. Fork the repo and create a feature branch off `main`.
2. Keep the PR small and focused on one change.
3. Write a clear description: what changed, why, and how you tested it.
4. Make sure nothing runtime-generated is committed (see [`.gitignore`](.gitignore));
   never commit `.env`, `data/`, or downloaded music.
5. By contributing, you agree your work is licensed under the project's
   [MIT License](LICENSE).

## Code of conduct

Participation is governed by our [Code of Conduct](CODE_OF_CONDUCT.md). Please
be kind.
