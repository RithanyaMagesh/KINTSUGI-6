# ---- Stage 1/2: frontend build (BACKEND_SPEC 8.2) --------------------------
# node_modules and the host-built dist are .dockerignore'd: the container's
# npm ci install is the only one that lands in the image.
FROM node:22-slim AS build

WORKDIR /build

# Dependency layer: manifests only, so Docker caches the node_modules.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Source layer (index.html, src/, public/, tsconfig, vite.config) -> /build/dist
# (vite's default outDir; package.json build = tsc && vite build).
COPY frontend/ ./
RUN npm run build

# ---- Stage 2/2: pinned uv runtime (unchanged from G0) ----------------------
# uv image pinned by digest: the python3.12-bookworm-slim variant has no versioned tag (verified 2026-09-28).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependency layer: manifests only, so Docker caches the wheels.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Application layer.
COPY cubesat ./cubesat
RUN uv sync --locked --no-dev

# Demo data (ENDGAME_PLAN risk #8): the scenario zoo plus the two committed
# canonical logs (4f2d81b). Per-run eval artifacts stay out via .dockerignore.
COPY data/scenarios ./data/scenarios
COPY data/logs/nominal.jsonl data/logs/two_failure.jsonl ./data/logs/

# Built frontend from stage 1: api.py resolves the static mount to
# _REPO_ROOT/frontend/dist, which is /app/frontend/dist in this image.
COPY --from=build /build/dist ./frontend/dist

ENV CUBESAT_LOG_DIR=/app/data/logs \
    PORT=8000
# Host-header allowlist (audit): the app accepts Host localhost/127.0.0.1 by
# default; publish the port beyond the operator's machine under another name
# only with CUBESAT_ALLOWED_HOSTS=<name(s)> added here.
EXPOSE 8000

RUN useradd --uid 1000 --no-create-home app
USER app

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["/app/.venv/bin/python", "-c", "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health', timeout=3).status == 200 else 1)"]

CMD ["/bin/sh", "-c", "exec /app/.venv/bin/uvicorn cubesat.api:app --host 0.0.0.0 --port ${PORT}"]
