"""FastAPI app. G0 skeleton: /health only; /api, /ws and static UI arrive in G5."""

from fastapi import FastAPI

from cubesat import __version__

app = FastAPI(title="cubesat-swarm", version=__version__)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
