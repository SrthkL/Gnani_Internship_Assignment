import uuid
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi import BackgroundTasks, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db import AsyncSessionLocal
from app.models import Upload
from app.schemas import UploadResponse
from app.storage import save_audio
from app.schemas import UploadResponse, UploadDetail
from app.config import BACKEND_DIR, settings
from app.gnani import transcribe_audio
from app.tasks import process_upload

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

@app.post(
    "/uploads/{upload_id}/transcribe",
    response_model=UploadResponse,
    status_code=202,
)
async def transcribe_upload(
    upload_id: str,
    background_tasks: BackgroundTasks,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Accept transcription and process it after returning the response."""

    # Lock the row so simultaneous requests cannot both start this job.
    upload = await db.get(Upload, upload_id, with_for_update=True)

    if upload is None:
        raise HTTPException(404, "Upload not found")

    if upload.status == "completed" and upload.transcript:
        response.status_code = 200
        return UploadResponse(id=upload.id, status=upload.status)

    if upload.status == "transcribing":
        raise HTTPException(409, "Recording is already being transcribed")

    storage_dir = Path(settings.STORAGE_DIR)
    if not storage_dir.is_absolute():
        storage_dir = BACKEND_DIR / storage_dir

    if not (storage_dir / upload.storage_key).is_file():
        raise HTTPException(404, "Stored audio file not found")

    # Reserve the job before releasing the database lock.
    upload.status = "transcribing"
    upload.progress = 0
    await db.commit()

    # Pass the ID; the task creates its own database session.
    background_tasks.add_task(process_upload, upload.id)

    return UploadResponse(id=upload.id, status=upload.status)

@app.get("/uploads", response_model=list[UploadDetail])
async def list_uploads(
    db: AsyncSession = Depends(get_db),
):
    """Return the latest 50 recordings, newest first."""

    result = await db.execute(
        select(Upload)
        .order_by(Upload.created_at.desc())
        .limit(50)
    )

    uploads = result.scalars().all()

    return [
        UploadDetail.model_validate(upload)
        for upload in uploads
    ]