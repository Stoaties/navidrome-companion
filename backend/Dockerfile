FROM python:3.12-slim

# ffmpeg: audio extraction/tagging. deno: JS runtime yt-dlp now needs for
# reliable YouTube extraction. curl/unzip/ca-certificates: to install deno.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl unzip ca-certificates \
    && curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The web app's own dependencies (FastAPI, uvicorn, ...).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install yt-dlp in an isolated pipx environment and expose its CLI on PATH.
# NOT pinned: YouTube changes frequently and only a current yt-dlp keeps working
# (a stale pin is what broke Spotify/YouTube downloads before). Rebuild to update.
# Spotify track lists are read from the public embed page in-process; only the
# audio download uses yt-dlp, so spotdl is no longer needed.
ENV PIPX_HOME=/opt/pipx \
    PIPX_BIN_DIR=/usr/local/bin
RUN pip install --no-cache-dir pipx \
    && pipx install yt-dlp

COPY app ./app

# Data (SQLite config db) and downloaded music live on mounted volumes.
ENV COMPANION_DATA_DIR=/data \
    MUSIC_DIR=/music \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
