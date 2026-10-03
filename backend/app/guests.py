"""Temporary guest jobs: no transcript or audio is saved in persistent storage."""
import asyncio
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from app.auth import now
from app.config import settings
from app.gnani import transcribe_audio
from app.llm import summarize_transcript
from app.schemas import UploadDetail
from app.tasks import failure_message


@dataclass
class GuestJob:
    id: str
    session_hash: str
    filename: str
    directory: str
    created_at: datetime
    expires_at: datetime
    status: str = "uploaded"
    progress: int = 0
    transcript: str | None = None
    summary: str | None = None
    error_message: str | None = None

    def detail(self):
        return UploadDetail.model_validate(self, from_attributes=True)


guest_jobs: dict[str, GuestJob] = {}


def get_guest(upload_id, session_hash):
    job = guest_jobs.get(upload_id)
    if not job or job.session_hash != session_hash or (job.expires_at <= now() and job.status not in {"transcribing", "summarizing"}):
        raise HTTPException(404, "Guest recording expired or was not found. Sign in to save future recordings.")
    return job


async def save_guest(file, upload_id, session_hash):
    if len(guest_jobs) >= 100:
        raise HTTPException(503, "Guest processing is busy. Please retry later.")
    directory = tempfile.mkdtemp(prefix="audio-notes-guest-")
    path = Path(directory) / ("audio" + Path(file.filename).suffix.lower())
    def copy():
        file.file.seek(0)
        with path.open("wb") as target:
            shutil.copyfileobj(file.file, target)
    try:
        await asyncio.to_thread(copy)
    except Exception:
        await asyncio.to_thread(shutil.rmtree, directory, ignore_errors=True)
        raise
    job = GuestJob(upload_id, session_hash, file.filename, directory, now(), now() + timedelta(minutes=settings.GUEST_RESULT_MINUTES))
    guest_jobs[upload_id] = job
    return job


async def process_guest(upload_id):
    job = guest_jobs.get(upload_id)
    if not job:
        return
    stage = "transcription"
    try:
        job.error_message = None
        if not job.transcript:
            async def progress(percent):
                job.progress = percent
            path = Path(job.directory) / ("audio" + Path(job.filename).suffix.lower())
            job.transcript = await transcribe_audio(str(path), on_progress=progress)
        job.status, job.progress = "summarizing", 100
        stage = "summary"
        job.summary = await summarize_transcript(job.transcript)
        job.status = "completed"
    except Exception as error:
        job.status = "failed"
        job.error_message = failure_message(error, stage)
    finally:
        job.expires_at = now() + timedelta(minutes=settings.GUEST_RESULT_MINUTES)
        if job.transcript:
            await asyncio.to_thread(shutil.rmtree, job.directory, ignore_errors=True)


async def cleanup_guests():
    for upload_id, job in list(guest_jobs.items()):
        if job.expires_at <= now() and job.status not in {"transcribing", "summarizing"}:
            guest_jobs.pop(upload_id, None)
            await asyncio.to_thread(shutil.rmtree, job.directory, ignore_errors=True)


async def forget_session(session_hash):
    for job in guest_jobs.values():
        if job.session_hash == session_hash:
            job.expires_at = now()
    await cleanup_guests()


async def cleanup_loop():
    while True:
        await cleanup_guests()
        await asyncio.sleep(60)
