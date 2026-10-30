# Stage 1: Build the React frontend
FROM node:22-slim AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend runner
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runner
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    CUBESAT_LOG_DIR=/app/data/logs \
    CUBESAT_ALLOWED_HOSTS="*"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install locked Python dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Copy application source code and scenarios
COPY cubesat/ ./cubesat/
COPY data/ ./data/
RUN uv sync --locked --no-dev

# Copy compiled frontend from Stage 1 into the location expected by cubesat/api.py
COPY --from=frontend-builder /build/dist ./frontend/dist

# Non-root user setup
RUN groupadd -g 1000 cubesat && \
    useradd -u 1000 -g cubesat -s /bin/bash -m cubesat && \
    mkdir -p /app/data/logs && \
    chown -R cubesat:cubesat /app
USER cubesat

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/health')" || exit 1

CMD ["sh", "-c", "uv run uvicorn cubesat.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
