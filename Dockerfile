# Ledgerline: one image with the API, the built web app and a seeded demo world.
# Fits a 512 MB instance: no heavy dependencies, page renders on demand, WORKERS=1 on free plans.

# --- 1. web app -----------------------------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
# Two web tests import the API schema at ../../../../backend/openapi.json (resolves to /backend).
COPY backend/openapi.json /backend/openapi.json
RUN npm run build

# --- 2. API + seeded demo world ---------------------------------------------------------------------
FROM python:3.12-slim AS app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /uvx /bin/

# OMP_THREAD_LIMIT=1: on a fractional-CPU instance Tesseract's OpenMP threads only contend for the
# same quota; a single thread reads a scan faster there.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/backend/.venv/bin:$PATH" \
    INVOICE_FONT_PATH=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf \
    OMP_THREAD_LIMIT=1 \
    DATA_DIR=/app/data \
    PORT=8000

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/ ./
COPY --from=web /web/dist ./app/static

# Generate the demo world and seed its history once, at build time, into the snapshot that a
# fresh container copies into DATA_DIR on startup (app/demo/snapshot.py). The offline reader is
# used for seeding only; the running app refuses LLM_PROVIDER=fake in production.
ARG APP_TODAY=2026-11-20
RUN APP_ENV=production LLM_PROVIDER=fake ALLOW_FAKE_LLM=1 APP_TODAY=${APP_TODAY} \
    DATA_DIR=/app/seed-data python -m app.demo.seed \
    && rm -f /app/seed-data/*.db-wal /app/seed-data/*.db-shm

RUN useradd --create-home --uid 10001 ledgerline \
    && mkdir -p /app/data \
    && chown -R ledgerline:ledgerline /app/data /app/seed-data
USER ledgerline

ENV APP_ENV=production \
    APP_TODAY=${APP_TODAY} \
    WORKERS=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/health', timeout=4)"
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
