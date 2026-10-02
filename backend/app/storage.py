import asyncio
import shutil
from pathlib import Path

from fastapi import UploadFile

from app.config import settings


async def save_audio(file: UploadFile, upload_id: str) -> str:
    # Preserve the extension, but use our generated ID as the filename.
    extension = Path(file.filename or "").suffix.lower()
    storage_key = f"audio/{upload_id}{extension}"

    # Resolve relative storage paths against the backend directory.
    backend_dir = Path(__file__).resolve().parent.parent
    storage_dir = Path(settings.STORAGE_DIR)

    if not storage_dir.is_absolute():
        storage_dir = backend_dir / storage_dir

    destination = storage_dir / storage_key

    def copy_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        file.file.seek(0)

        try:
            with destination.open("wb") as target:
                shutil.copyfileobj(file.file, target)
        except Exception:
            # Remove a partially written file if copying fails.
            destination.unlink(missing_ok=True)
            raise

    # Run blocking filesystem work outside the async event loop.
    await asyncio.to_thread(copy_file)

    return storage_key