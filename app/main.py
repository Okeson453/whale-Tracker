"""FastAPI entrypoint — Session 1 scaffold."""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from fastapi import FastAPI

from app.config import validate_startup_config
from app.ingestion.webhook_receiver import router as webhook_router
from app.state.db import init_db
from app.utils.logging_config import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    # Fail fast on a malformed settings.yaml or DATABASE_URL rather than
    # discovering it later as a runtime KeyError or a failed DB connection.
    validate_startup_config()
    await init_db()
    yield


app = FastAPI(title="Whale Copy-Trading Bot", lifespan=lifespan)
app.include_router(webhook_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)
