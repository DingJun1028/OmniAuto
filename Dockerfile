# AI Station — container image
# Runs the FastAPI control center. ffmpeg is installed at runtime because
# the rendering engine (src/renderer.py) shells out to it.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# system deps: ffmpeg (required by renderer + TTS silent fallback) and a
# CJK font so burned captions render Chinese on Linux (not just Windows).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# persist generated videos + sqlite db across container restarts
VOLUME ["/app/storage"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health').status==200 else 1)"

CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"]
