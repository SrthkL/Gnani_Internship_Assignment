import json
import mimetypes
from pathlib import Path
import asyncio
import httpx
import shutil

from app.audio import prepare_audio

from app.config import settings


async def create_job(audio_path: str) -> str:
    """Upload one recording to Gnani and return its provider job ID."""

    if not settings.GNANI_API_KEY:
        raise ValueError("GNANI_API_KEY is missing")

    path = Path(audio_path)

    # Larger recordings will need chunking, which we will add later.
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("Audio is too large for direct upload")

    config = {
        "model": "gnani-prisma-v2.5",
        "language_code": settings.GNANI_LANGUAGE,
        "mode": "transcribe",
    }

    content_type = (
        mimetypes.guess_type(path.name)[0]
        or "application/octet-stream"
    )

    async with httpx.AsyncClient(timeout=120) as client:
        with path.open("rb") as audio:
            response = await client.post(
                f"{settings.GNANI_BASE_URL.rstrip('/')}/stt/v3/batch/jobs",
                headers={"X-API-Key-ID": settings.GNANI_API_KEY},
                files={
                    "files": (path.name, audio, content_type),
                    "config": (
                        None,
                        json.dumps(config),
                        "application/json",
                    ),
                },
            )

        response.raise_for_status()
        return response.json()["job_id"]

async def start_job(job_id: str) -> None:
    """Tell Gnani to begin processing an already-created job."""

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{settings.GNANI_BASE_URL.rstrip('/')}/stt/v3/batch/jobs/{job_id}/start",
            headers={"X-API-Key-ID": settings.GNANI_API_KEY},
        )

        response.raise_for_status()

async def wait_for_completion(
    job_id: str,
    timeout_seconds: int = 900,
) -> None:
    """Wait for completion, stopping on failure or timeout."""

    # Do not poll faster than Gnani's recommended 10-second interval.
    poll_interval = max(10, settings.GNANI_POLL_SECONDS)

    async with httpx.AsyncClient(timeout=30) as client:
        # Limit the entire wait, including HTTP requests and pauses.
        async with asyncio.timeout(timeout_seconds):
            while True:
                response = await client.get(
                    f"{settings.GNANI_BASE_URL.rstrip('/')}/stt/v3/batch/jobs/{job_id}",
                    headers={"X-API-Key-ID": settings.GNANI_API_KEY},
                )
                response.raise_for_status()

                status = response.json()["status"]

                if status == "COMPLETED":
                    return

                if status in {
                    "FAILED",
                    "CANCELLED",
                    "START_FAILED",
                    "PARTIAL_FAILURE",
                }:
                    raise RuntimeError(
                        f"Gnani job ended with status: {status}"
                    )

                await asyncio.sleep(poll_interval)

async def fetch_transcript(job_id: str) -> str:
    """Retrieve the transcript text for our single-file job."""

    async with httpx.AsyncClient(
        timeout=120,
        follow_redirects=True,
    ) as client:
        # Ask Gnani for the completed file's download link.
        response = await client.get(
            f"{settings.GNANI_BASE_URL.rstrip('/')}/stt/v3/batch/jobs/{job_id}/files",
            headers={"X-API-Key-ID": settings.GNANI_API_KEY},
            params={"status": "COMPLETED"},
        )
        response.raise_for_status()

        files = response.json().get("data", [])

        if not files:
            raise RuntimeError("Gnani returned no completed files")

        transcript_url = files[0].get("transcript_url")

        if not transcript_url:
            raise RuntimeError("Transcript download link is missing")

        # The signed download URL does not require our API key.
        result = await client.get(transcript_url)
        result.raise_for_status()

        transcript = result.json().get("full_transcript")

        if not isinstance(transcript, str) or not transcript.strip():
            raise RuntimeError("Gnani returned an empty transcript")

        return transcript

async def transcribe_audio(audio_path: str) -> str:
    """Prepare audio, transcribe its chunks, and combine their text."""

    directory, chunks = await prepare_audio(audio_path)

    try:
        transcripts = []

        # Process chunks sequentially to preserve recording order.
        for chunk_path in chunks:
            job_id = await create_job(chunk_path)
            await start_job(job_id)
            await wait_for_completion(job_id)

            text = await fetch_transcript(job_id)
            transcripts.append(text)

        return "\n".join(transcripts)

    finally:
        # Remove temporary chunks even if transcription fails.
        await asyncio.to_thread(
            shutil.rmtree,
            directory,
            ignore_errors=True,
        )