"""FastAPI entrypoint — Session 1 scaffold."""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

import httpx
from fastapi import FastAPI

from app.config import env, validate_startup_config
from app.ingestion.webhook_receiver import router as webhook_router
from app.state.db import init_db
from app.utils.logging_config import configure_logging

logger = logging.getLogger(__name__)


async def send_startup_message() -> None:
    """Send a Telegram message to confirm the bot is alive and running."""
    if not env.telegram_bot_token or not env.telegram_chat_id:
        logger.info("Telegram credentials not configured; skipping startup message")
        return

    try:
        async with httpx.AsyncClient() as client:
            url = f"https://api.telegram.org/bot{env.telegram_bot_token}/sendMessage"
            payload = {
                "chat_id": env.telegram_chat_id,
                "text": "🤖 Whale Tracker is online and monitoring for whale transactions.",
                "parse_mode": "HTML",
            }
            response = await client.post(url, json=payload, timeout=10.0)
            response.raise_for_status()
            logger.info("Startup message sent to Telegram chat")
    except Exception as exc:
        logger.error("Failed to send startup message to Telegram: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    # Fail fast on a malformed settings.yaml or DATABASE_URL rather than
    # discovering it later as a runtime KeyError or a failed DB connection.
    validate_startup_config()
    await init_db()
    await send_startup_message()
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
