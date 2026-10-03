import asyncio
import tempfile
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BACKEND_DIR, settings
from app.models import Upload


def check_storage() -> None:
    storage = Path(settings.STORAGE_DIR)
    if not storage.is_absolute():
        storage = BACKEND_DIR / storage
    storage.mkdir(parents=True, exist_ok=True)
    # Test a real write: existence alone does not verify volume permissions.
    with tempfile.TemporaryFile(dir=storage) as probe:
        probe.write(b"ready")
        probe.flush()


async def check_readiness(db: AsyncSession) -> None:
    try:
        # LIMIT 0 verifies all mapped columns without reading recordings.
        async with asyncio.timeout(10):
            await db.execute(select(Upload).limit(0))
            await asyncio.to_thread(check_storage)
    except Exception:
        # Connection errors can contain credentials; keep them out of responses.
        raise HTTPException(503, "Database or audio storage is unavailable") from None
