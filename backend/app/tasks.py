import logging
from pathlib import Path

from app.config import BACKEND_DIR, settings
from app.db import AsyncSessionLocal
from app.gnani import transcribe_audio
from app.models import Upload


logger = logging.getLogger(__name__)


async def process_upload(upload_id: str) -> None:
    """Transcribe a recording and save its result."""

    async with AsyncSessionLocal() as db:
        upload = await db.get(Upload, upload_id)

        if upload is None:
            return

        upload.status = "transcribing"
        await db.commit()

        try:
            storage_dir = Path(settings.STORAGE_DIR)
            if not storage_dir.is_absolute():
                storage_dir = BACKEND_DIR / storage_dir

            audio_path = storage_dir / upload.storage_key

            if not audio_path.is_file():
                raise FileNotFoundError("Stored recording is missing")

            transcript = await transcribe_audio(str(audio_path))

        except Exception as error:
            upload.status = "failed"
            logger.error(
                "Transcription failed for upload %s: %s",
                upload_id,
                type(error).__name__,
            )

        else:
            upload.transcript = transcript
            upload.status = "completed"
            upload.progress = 100

        await db.commit()