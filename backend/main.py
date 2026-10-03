import uuid
import asyncio
import secrets
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi import BackgroundTasks, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from starlette.middleware.sessions import SessionMiddleware
from app.db import get_db
from app.models import Upload, BrowserSession
from app.storage import save_audio
from app.schemas import UploadResponse, UploadDetail
from app.config import BACKEND_DIR, settings
from app.tasks import process_upload
from app.health import check_readiness
from app.auth import router as auth_router, current_session, require_user, check_origin, validate_auth_settings
from app.guests import cleanup_loop, cleanup_guests, get_guest, save_guest, process_guest

@asynccontextmanager
async def lifespan(app):
    validate_auth_settings()
    cleaner = asyncio.create_task(cleanup_loop())
    try:
        yield
    finally:
        cleaner.cancel()
        with suppress(asyncio.CancelledError):
            await cleaner
        from app.guests import guest_jobs, cleanup_guests
        from app.auth import now
        for job in guest_jobs.values():
            job.expires_at = now()
            job.status = "failed"
        await cleanup_guests()


app = FastAPI(title="Audio Notes API", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.AUTH_SECRET.get_secret_value() or secrets.token_urlsafe(32),
    session_cookie="google_oauth_state", max_age=600,
    https_only=settings.APP_ENV == "production", same_site="lax",
)
app.include_router(auth_router)


@app.middleware("http")
async def private_responses(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/uploads", "/auth")):
        response.headers["Cache-Control"] = "no-store"
    if request.url.path == "/auth/google/callback":
        # Uvicorn logs the scope after this response; omit OAuth codes/state.
        request.scope["query_string"] = b""
    return response


@app.get("/live")
async def live(): #checking wether the API is responding
    return {"status": "ok"}


@app.get("/ready")
async def ready(db: AsyncSession = Depends(get_db)):
    """Verify the database schema and writable audio storage for deployment."""
    await check_readiness(db)
    return {"status": "ready"}


@app.post("/uploads", response_model=UploadResponse, status_code=201, dependencies=[Depends(check_origin)])
async def create_upload(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    session: BrowserSession = Depends(current_session),
):
    """Save an Audio recording and create its database"""
    filename = file.filename or ""
    extension = Path(filename).suffix.lower()

    if extension not in {".wav", ".mp3", ".m4a", ".flac", ".ogg"}:
        raise HTTPException(
            status_code=415,
            detail="Unsupported audio format",
        )

    if not file.size or file.size > 50 * 1024 * 1024:
        raise HTTPException(413, "Choose a non-empty audio file up to 50 MB.")

    #use a generated ID so identical filenames dont overwrite each other
    upload_id = str(uuid.uuid4())
    if not session.user_id:
        # Atomic reservation prevents two parallel requests sharing the allowance.
        reserved = await db.execute(
            update(BrowserSession)
            .where(BrowserSession.token_hash == session.token_hash, BrowserSession.guest_used.is_(False))
            .values(guest_used=True)
        )
        if reserved.rowcount != 1:
            raise HTTPException(403, "Your guest recording has been used. Sign in to upload more and save history.")
        guest = None
        try:
            guest = await save_guest(file, upload_id, session.token_hash)
            await db.commit()
        except Exception as error:
            await db.rollback()
            if guest is not None:
                from app.auth import now
                guest.expires_at = now()
                await cleanup_guests()
            if isinstance(error, HTTPException):
                raise
            raise HTTPException(503, "Audio storage or database is unavailable. Please retry.") from None
        return UploadResponse(id=guest.id, status=guest.status)

    try:
        storage_key = await save_audio(file, upload_id)
    except OSError:
        raise HTTPException(503, "Audio storage is unavailable. Please retry.") from None

    #upload means saved not yet transcribed
    upload = Upload(
        id=upload_id,
        user_id=session.user_id,
        filename=filename,
        storage_key=storage_key,
        status="uploaded",
    )

    db.add(upload)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        storage_dir = Path(settings.STORAGE_DIR)
        if not storage_dir.is_absolute():
            storage_dir = BACKEND_DIR / storage_dir
        await asyncio.to_thread((storage_dir / storage_key).unlink, missing_ok=True)
        raise HTTPException(503, "Database is unavailable. Please retry.") from None

    return UploadResponse(
        id=upload.id,
        status=upload.status,
    )

@app.get("/uploads/{upload_id}", response_model=UploadDetail)
async def get_upload(
    upload_id: str,
    db: AsyncSession = Depends(get_db),
    session: BrowserSession = Depends(current_session),
):
    """Retrieve a recording's metadata and available transcript."""

    if not session.user_id:
        return get_guest(upload_id, session.token_hash).detail()

    # IDs are not authorization; always verify the account owns the row.
    upload = await db.get(Upload, upload_id)

    if upload is None or upload.user_id != session.user_id:
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
    dependencies=[Depends(check_origin)],
)
async def transcribe_upload(
    upload_id: str,
    background_tasks: BackgroundTasks,
    response: Response,
    db: AsyncSession = Depends(get_db),
    session: BrowserSession = Depends(current_session),
):
    """Accept transcription and process it after returning the response."""

    if not session.user_id:
        guest = get_guest(upload_id, session.token_hash)
        if guest.status == "completed":
            response.status_code = 200
            return UploadResponse(id=guest.id, status=guest.status)
        if guest.status in {"transcribing", "summarizing"}:
            raise HTTPException(409, "Recording is already being processed")
        guest.status = "transcribing"
        background_tasks.add_task(process_guest, guest.id)
        return UploadResponse(id=guest.id, status=guest.status)

    # Lock the row so simultaneous requests cannot both start this job.
    upload = await db.get(Upload, upload_id, with_for_update=True)

    if upload is None or upload.user_id != session.user_id:
        raise HTTPException(404, "Upload not found")

    if upload.status == "completed" and upload.transcript and upload.summary:
        response.status_code = 200
        return UploadResponse(id=upload.id, status=upload.status)

    if upload.status in {"transcribing", "summarizing"}:
        raise HTTPException(409, "Recording is already being processed")

    storage_dir = Path(settings.STORAGE_DIR)
    if not storage_dir.is_absolute():
        storage_dir = BACKEND_DIR / storage_dir

    if not upload.transcript and not (storage_dir / upload.storage_key).is_file():
        raise HTTPException(404, "Stored audio file not found")

    # Reserve the job before releasing the database lock.
    upload.status = "transcribing"
    upload.progress = 100 if upload.transcript else 0
    await db.commit()

    # Pass the ID; the task creates its own database session.
    background_tasks.add_task(process_upload, upload.id)

    return UploadResponse(id=upload.id, status=upload.status)

@app.get("/uploads", response_model=list[UploadDetail])
async def list_uploads(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_user),
):
    """Return the latest 50 recordings, newest first."""

    result = await db.execute(
        select(Upload)
        .where(Upload.user_id == user_id)
        .order_by(Upload.created_at.desc())
        .limit(50)
    )

    uploads = result.scalars().all()

    return [
        UploadDetail.model_validate(upload)
        for upload in uploads
    ]

