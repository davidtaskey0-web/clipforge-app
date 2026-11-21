FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip yt-dlp faster-whisper

COPY . /app

RUN mkdir -p /tmp/clipforge_exports && chmod -R 777 /app /tmp/clipforge_exports

ENV PORT=7860
ENV PYTHONUNBUFFERED=1
EXPOSE 7860

CMD ["python", "-u", "/app/clipforge_app.py"]
