from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app import tasks
import main
from app.db import Base
from app.models import Upload
from app.auth import new_session
from app.models import User
from fastapi import Response
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def mock_session(monkeypatch, upload):
    session = SimpleNamespace(
        get=AsyncMock(return_value=upload),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )

    @asynccontextmanager
    async def factory():
        yield session

    monkeypatch.setattr(tasks, "AsyncSessionLocal", factory)
    return session


@pytest.mark.asyncio
async def test_failed_provider_request_saves_a_safe_actionable_error(monkeypatch, tmp_path):
    (tmp_path / "recording.wav").write_bytes(b"test-audio")
    upload = SimpleNamespace(
        status="transcribing", transcript=None, summary=None,
        progress=0, error_message=None, storage_key="recording.wav",
    )
    session = mock_session(monkeypatch, upload)
    monkeypatch.setattr(tasks.settings, "STORAGE_DIR", str(tmp_path))
    response = httpx.Response(
        429, request=httpx.Request("POST", "https://example.test/start?key=do-not-expose"),
    )
    error = httpx.HTTPStatusError("private provider response", request=response.request, response=response)
    monkeypatch.setattr(tasks, "transcribe_audio", AsyncMock(side_effect=error))
    summary = AsyncMock()
    monkeypatch.setattr(tasks, "summarize_transcript", summary)

    await tasks.process_upload("test-upload")

    assert upload.status == "failed"
    assert "rate limit" in upload.error_message
    assert "do-not-expose" not in upload.error_message
    assert upload.transcript is None
    session.rollback.assert_awaited_once()
    summary.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_uses_saved_transcript_without_calling_provider(monkeypatch):
    upload = SimpleNamespace(
        status="failed", transcript="The saved transcript.", summary=None,
        progress=100, error_message="Old failure", storage_key="missing.wav",
    )
    mock_session(monkeypatch, upload)
    transcription = AsyncMock()
    monkeypatch.setattr(tasks, "transcribe_audio", transcription)
    summary = AsyncMock(return_value="The summary.")
    monkeypatch.setattr(tasks, "summarize_transcript", summary)

    await tasks.process_upload("test-upload")

    assert upload.status == "completed"
    assert upload.transcript == "The saved transcript."
    assert upload.summary == "The summary."
    assert upload.error_message is None
    transcription.assert_not_awaited()
    summary.assert_awaited_once_with("The saved transcript.")


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_later_chunk", [False, True])
async def test_chunk_progress_is_visible_to_polling_and_survives_failure(
    monkeypatch, tmp_path, fail_later_chunk,
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'progress.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    (tmp_path / "recording.wav").write_bytes(b"test-audio")
    async with sessions() as db:
        db.add(User(id="progress-owner", google_sub="progress-google", email="test@example.test", name="Test"))
        cookie_response = Response()
        await new_session(db, cookie_response, "progress-owner")
        db.add(Upload(
            id="progress-test", filename="recording.wav", storage_key="recording.wav",
            status="transcribing", progress=0, user_id="progress-owner",
        ))
        await db.commit()

    async def dependency():
        async with sessions() as db:
            yield db

    main.app.dependency_overrides[main.get_db] = dependency
    monkeypatch.setattr(tasks, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(tasks.settings, "STORAGE_DIR", str(tmp_path))
    summary = AsyncMock(return_value="Saved summary.")
    monkeypatch.setattr(tasks, "summarize_transcript", summary)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test",
    ) as client:
        client.cookies.extract_cookies(httpx.Response(200, headers={"set-cookie": cookie_response.headers["set-cookie"]}, request=httpx.Request("GET", "http://test")))
        async def fake_transcribe(audio_path, on_progress):
            await on_progress(50)
            # A separate API session must see progress before processing ends.
            response = await client.get("/uploads/progress-test")
            assert response.status_code == 200
            assert response.json()["progress"] == 50
            assert response.json()["status"] == "transcribing"
            assert response.json()["transcript"] is None
            if fail_later_chunk:
                raise RuntimeError("Later chunk failed")
            await on_progress(100)
            return "Saved transcript."

        monkeypatch.setattr(tasks, "transcribe_audio", fake_transcribe)
        try:
            await tasks.process_upload("progress-test")
            result = (await client.get("/uploads/progress-test")).json()
            assert result["progress"] == (50 if fail_later_chunk else 100)
            assert result["status"] == ("failed" if fail_later_chunk else "completed")
            if fail_later_chunk:
                summary.assert_not_awaited()
            else:
                assert result["transcript"] == "Saved transcript."
                assert result["summary"] == "Saved summary."
        finally:
            main.app.dependency_overrides.clear()
            await engine.dispose()
