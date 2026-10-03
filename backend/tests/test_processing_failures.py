from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app import tasks


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
