import logging
from pathlib import Path

from app.config import BACKEND_DIR, settings
from app.db import AsyncSessionLocal
from app.gnani import transcribe_audio
from app.models import Upload
from app.llm import summarize_transcript


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


async def process_upload(upload_id: str) -> None:
    """Transcribe and summarize, preserving completed transcription."""

    async with AsyncSessionLocal() as db:
        upload = await db.get(Upload, upload_id)

        if upload is None:
            return

        try:
            # Reuse saved transcription when retrying a failed summary.
            if not upload.transcript:
                upload.status = "transcribing"
                await db.commit()

                storage_dir = Path(settings.STORAGE_DIR)
                if not storage_dir.is_absolute():
                    storage_dir = BACKEND_DIR / storage_dir

                audio_path = storage_dir / upload.storage_key

                if not audio_path.is_file():
                    raise FileNotFoundError("Stored recording is missing")

                upload.transcript = await transcribe_audio(str(audio_path))

            # Persist the transcript before contacting the LLM.
            upload.progress = 100
            upload.status = "summarizing"
            await db.commit()

            upload.summary = await summarize_transcript(upload.transcript)
            upload.status = "completed"
            await db.commit()

        except Exception as error:
            # Recover the session before trying to save the failed state.
            await db.rollback()
            upload = await db.get(Upload, upload_id)

            if upload is not None:
                upload.status = "failed"
                await db.commit()

            logger.error(
                "Processing failed for upload %s: %s",
                upload_id,
                type(error).__name__,
            )

def split_transcript(text: str, max_bytes: int = 3000) -> list[str]:
    """Split text into bounded pieces without dropping Unicode characters."""

    if max_bytes < 4:
        raise ValueError("Chunk limit must accommodate a UTF-8 character")

    chunks = []
    characters = []
    current_bytes = 0

    for character in text:
        character_bytes = len(character.encode("utf-8"))

        if current_bytes + character_bytes > max_bytes:
            chunks.append("".join(characters))
            characters = []
            current_bytes = 0

        characters.append(character)
        current_bytes += character_bytes

    if characters:
        chunks.append("".join(characters))

    return chunks