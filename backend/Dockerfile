FROM python:3.12-slim

# ffmpeg is required by yt-dlp/spotdl for audio extraction and tagging.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Data (SQLite config db) and downloaded music live on mounted volumes.
ENV COMPANION_DATA_DIR=/data \
    MUSIC_DIR=/music \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
