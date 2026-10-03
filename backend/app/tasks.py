import logging
import httpx
from pathlib import Path

from app.config import BACKEND_DIR, settings
from app.db import AsyncSessionLocal
from app.gnani import transcribe_audio
from app.models import Upload
from app.llm import summarize_transcript


logger = logging.getLogger(__name__)


def failure_message(error: Exception, stage: str) -> str:
    """Return actionable errors without exposing keys, URLs, or provider bodies."""
    service = "Speech provider" if stage == "transcription" else "Summary service"
    if isinstance(error, httpx.HTTPStatusError):
        code = error.response.status_code
        if code == 429:
            return f"{service} rate limit exceeded after automatic retries. Please retry shortly."
        if code in {401, 403}:
            return f"{service} rejected authentication or access (HTTP {code}). Check its configuration."
        return f"{service} request failed (HTTP {code}). Please retry."
    if isinstance(error, (httpx.TimeoutException, TimeoutError)):
        return f"{service} timed out. Please retry."
    if isinstance(error, httpx.TransportError):
        return f"Could not reach the {service.lower()}. Check that it is available."
    if isinstance(error, FileNotFoundError):
        return "The original recording is missing. Please upload it again."
    if isinstance(error, NotImplementedError):
        return "Audio conversion could not start. Run the Windows backend without --reload."
    if isinstance(error, ValueError) and str(error) in {
        "Audio could not be decoded", "Audio produced no usable chunks",
    }:
        return "This recording could not be decoded. Please upload a valid audio file."
    return f"{stage.capitalize()} failed ({type(error).__name__}). Check the backend log."


async def process_upload(upload_id: str) -> None:
    """Transcribe and summarize, preserving completed transcription."""

    async with AsyncSessionLocal() as db:
        upload = await db.get(Upload, upload_id)

        if upload is None:
            return

        stage = "transcription"
        try:
            upload.error_message = None
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

                async def save_progress(percent: int) -> None:
                    upload.progress = percent
                    # Make each completed chunk visible to polling requests.
                    await db.commit()

                upload.transcript = await transcribe_audio(
                    str(audio_path), on_progress=save_progress,
                )

            # Persist the transcript before contacting the LLM.
            upload.progress = 100
            upload.status = "summarizing"
            await db.commit()

            stage = "summary"
            upload.summary = await summarize_transcript(upload.transcript)
            upload.status = "completed"
            await db.commit()

        except Exception as error:
            # Recover the session before trying to save the failed state.
            await db.rollback()
            upload = await db.get(Upload, upload_id)

            if upload is not None:
                upload.status = "failed"
                upload.error_message = failure_message(error, stage)
                await db.commit()

            logger.error(
                "Processing failed for upload %s: %s",
                upload_id,
                failure_message(error, stage),
            )
