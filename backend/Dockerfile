FROM python:3.12-slim

# ffmpeg is required by yt-dlp/spotdl for audio extraction and tagging.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The web app's own dependencies (FastAPI, uvicorn, ...).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install the download tools in isolated pipx environments and expose their
# CLIs on PATH (/usr/local/bin). This keeps spotdl's strict pins (fastapi<0.104,
# etc.) fully separate from the web app, which calls them as subprocesses.
ENV PIPX_HOME=/opt/pipx \
    PIPX_BIN_DIR=/usr/local/bin
RUN pip install --no-cache-dir pipx \
    && pipx install spotdl==4.2.11 \
    && pipx install yt-dlp==2024.12.23

COPY app ./app

# Data (SQLite config db) and downloaded music live on mounted volumes.
ENV COMPANION_DATA_DIR=/data \
    MUSIC_DIR=/music \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
