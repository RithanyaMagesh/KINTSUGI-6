FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependency layer: manifests only, so Docker caches the wheels.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application layer.
COPY cubesat ./cubesat
RUN uv sync --frozen --no-dev

ENV PORT=8000
EXPOSE 8000

RUN useradd --uid 1000 --no-create-home app
USER app

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["/app/.venv/bin/python", "-c", "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health', timeout=3).status == 200 else 1)"]

CMD ["/bin/sh", "-c", "exec /app/.venv/bin/uvicorn cubesat.api:app --host 0.0.0.0 --port ${PORT}"]
