FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl tesseract-ocr tesseract-ocr-ara poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# forsah.py only ever launches chromium headless=True, which Playwright serves via
# chromium-headless-shell — drop the full (headed) Chrome build and ffmpeg (no video
# recording) to keep the image smaller.
RUN playwright install --with-deps chromium \
    && rm -rf /root/.cache/ms-playwright/chromium-[0-9]* \
              /root/.cache/ms-playwright/ffmpeg-* \
    && rm -rf /var/lib/apt/lists/*

COPY app ./app
COPY scripts ./scripts

VOLUME ["/app/data"]

ENV PORT=8000
EXPOSE 8000

# /api/status is auth-protected (401 when not logged in) — either response code means the app is up.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -s -o /dev/null -w '%{http_code}' http://localhost:${PORT}/api/status | grep -qE '^(200|401)$'

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
