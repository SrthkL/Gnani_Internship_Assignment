import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal
from app.models import Upload
from app.schemas import UploadResponse
from app.storage import save_audio


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