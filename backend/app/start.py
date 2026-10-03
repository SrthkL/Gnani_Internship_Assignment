"""Single-instance container entry point; ordinary local startup stays unchanged."""

import asyncio
import os
from urllib.parse import urlsplit

import uvicorn
from sqlalchemy import update

from app.config import settings
from app.db import Base, engine
from app.health import check_storage
from app.models import Upload


def validate_deployment() -> None:
    if settings.APP_ENV != "production":
        return
    if not settings.GNANI_API_KEY.strip():
        raise RuntimeError("Set GNANI_API_KEY before deploying")
    endpoint = urlsplit(settings.LLM_BASE_URL)
    if endpoint.scheme not in {"http", "https"} or not endpoint.hostname:
        raise RuntimeError("Set a valid LLM_BASE_URL before deploying")
    if endpoint.hostname.lower() in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("LLM_BASE_URL must point to a hosted service, not localhost")


async def initialize() -> None:
    validate_deployment()
    try:
        await asyncio.to_thread(check_storage)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            # A stopped in-process task cannot resume itself. Allow manual retry,
            # preserving completed transcripts, rather than leaving it stuck.
            # Only safe with one instance and a database dedicated to this app.
            await connection.execute(
                update(Upload)
                .where(Upload.status.in_(["transcribing", "summarizing"]))
                .values(
                    status="failed",
                    error_message="Processing was interrupted by a server restart. Please retry.",
                )
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(initialize())
    uvicorn.run(
        "main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8010")),
        workers=1,
        timeout_graceful_shutdown=120,
    )
