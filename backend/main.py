import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal
from app.models import Upload
from app.schemas import UploadResponse
from app.storage import save_audio
from app.schemas import UploadResponse, UploadDetail
from app.config import BACKEND_DIR, settings
from app.gnani import transcribe_audio
app = FastAPI(title="Audio Notes API")


# Give each request its own database session.
async def get_db():
    """Provide database session and close it after the request"""
    async with AsyncSessionLocal() as session:
        yield session


@app.get("/live")
async def live(): #checking wether the API is responding
    return {"status": "ok"}


@app.post("/uploads", response_model=UploadResponse, status_code=201)
async def create_upload(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
):
    """Save an Audio recording and create its database"""
    filename = file.filename or ""
    extension = Path(filename).suffix.lower()

    if extension not in {".wav", ".mp3", ".m4a", ".flac", ".ogg"}:
        raise HTTPException(
            status_code=415,
            detail="Unsupported audio format",
        )

    #use a generated ID so identical filenames dont overwrite each other
    upload_id = str(uuid.uuid4())
    storage_key = await save_audio(file, upload_id)

    #upload means saved not yet transcribed
    upload = Upload(
        id=upload_id,
        filename=filename,
        storage_key=storage_key,
        status="uploaded",
    )

    db.add(upload)
    await db.commit()

    return UploadResponse(
        id=upload.id,
        status=upload.status,
    )

@app.get("/uploads/{upload_id}", response_model=UploadDetail)
async def get_upload(
    upload_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a recording's metadata and available transcript."""

    # Look up the recording using its primary key.
    upload = await db.get(Upload, upload_id)

    if upload is None:
        raise HTTPException(
            status_code=404,
            detail="Upload not found",
        )

    # Read the database object's attributes into our public response schema.
    return UploadDetail.model_validate(upload)

@app.post("/uploads/{upload_id}/transcribe", response_model=UploadDetail)
async def transcribe_upload(
    upload_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Transcribe a saved recording and persist its text."""

    upload = await db.get(Upload, upload_id)

    if upload is None:
        raise HTTPException(404, "Upload not found")

    # Reuse a finished transcript instead of paying to transcribe again.
    if upload.status == "completed" and upload.transcript:
        return UploadDetail.model_validate(upload)

    if upload.status == "transcribing":
        raise HTTPException(409, "Recording is already being transcribed")

    # Locate the audio using the same storage root as save_audio.
    storage_dir = Path(settings.STORAGE_DIR)
    if not storage_dir.is_absolute():
        storage_dir = BACKEND_DIR / storage_dir

    audio_path = storage_dir / upload.storage_key

    if not audio_path.is_file():
        raise HTTPException(404, "Stored audio file not found")

    # Persist the state before waiting for the remote provider.
    upload.status = "transcribing"
    await db.commit()

    try:
        transcript = await transcribe_audio(str(audio_path))
    except Exception:
        upload.status = "failed"
        await db.commit()
        raise HTTPException(502, "Transcription failed")

    upload.transcript = transcript
    upload.status = "completed"
    await db.commit()

    return UploadDetail.model_validate(upload)


