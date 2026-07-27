# syntax=docker/dockerfile:1
# Padrão = COM OpenCLIP (você pediu). Máquina: 4GB+ RAM.
# Sem CLIP (mais barato): no Railway mude dockerfilePath para "Dockerfile.lite"
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=3001 \
    CLIP_ENABLED=true \
    CODE_VIEWER_ENABLED=false \
    FLASK_ENV=production \
    SESSION_COOKIE_SECURE=true \
    HF_HOME=/app/.cache/huggingface \
    TORCH_HOME=/app/.cache/torch

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-clip.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r requirements-clip.txt

COPY backend ./backend
COPY frontend ./frontend
COPY .env.example ./.env.example

RUN mkdir -p /app/data /app/frontend/fotos/slots /app/.cache/huggingface /app/.cache/torch

EXPOSE 3001

CMD ["sh", "-c", "waitress-serve --host=0.0.0.0 --port=${PORT:-3001} backend.server:app"]
