from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import main
from app import health, llm, start
from app.config import settings
from app.models import Upload


@pytest.mark.asyncio
async def test_container_restart_preserves_results_and_allows_interrupted_job_retry(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'deployment.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(start, "engine", engine)
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path / "audio-volume"))
    await start.initialize()
    async with sessions() as db:
        for name, status in [("speech", "transcribing"), ("notes", "summarizing"), ("done", "completed"), ("new", "uploaded")]:
            db.add(Upload(id=name, filename=f"{name}.wav", storage_key=f"audio/{name}.wav", status=status, transcript="saved speech" if name == "notes" else None))
        await db.commit()
    await start.initialize()
    async with sessions() as db:
        rows = {row.id: row for row in (await db.execute(select(Upload))).scalars()}
        assert rows["speech"].status == rows["notes"].status == "failed"
        assert "restart" in rows["speech"].error_message
        assert rows["notes"].transcript == "saved speech"
        assert rows["done"].status == "completed"
        assert rows["new"].status == "uploaded"
        await health.check_readiness(db)
    assert list((tmp_path / "audio-volume").iterdir()) == []
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["database", "storage"])
async def test_readiness_returns_503_without_exposing_configuration(monkeypatch, failure):
    database = SimpleNamespace(execute=AsyncMock())
    if failure == "database":
        database.execute.side_effect = RuntimeError("postgres://private:secret@database")
    def probe():
        if failure == "storage":
            raise PermissionError("private disk path")
    monkeypatch.setattr(health, "check_storage", probe)
    async def dependency():
        yield database
    main.app.dependency_overrides[main.get_db] = dependency
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            response = await client.get("/ready")
            assert response.status_code == 503
            assert response.json() == {"detail": "Database or audio storage is unavailable"}
            assert (await client.get("/live")).status_code == 200
    finally:
        main.app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("api_key", ["", "test-hosted-key"])
async def test_summary_client_supports_hosted_auth_and_local_no_auth(monkeypatch, api_key):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Saved summary"}}]})
    original_client = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(settings, "LLM_API_KEY", SecretStr(api_key))
    monkeypatch.setattr(settings, "LLM_BASE_URL", "https://summary.example/v1")
    assert await llm.summarize_transcript("Source speech") == "Saved summary"
    assert str(requests[0].url) == "https://summary.example/v1/chat/completions"
    assert requests[0].headers.get("Authorization") == (f"Bearer {api_key}" if api_key else None)


def test_production_rejects_laptop_llm_and_missing_speech_credentials(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "GNANI_API_KEY", "")
    with pytest.raises(RuntimeError, match="GNANI_API_KEY"):
        start.validate_deployment()
    monkeypatch.setattr(settings, "GNANI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "LLM_BASE_URL", "http://localhost:11434/v1")
    with pytest.raises(RuntimeError, match="hosted service"):
        start.validate_deployment()
    monkeypatch.setattr(settings, "LLM_BASE_URL", "https://summary.example/v1")
    monkeypatch.setattr(settings, "AUTH_SECRET", SecretStr(""))
    with pytest.raises(RuntimeError, match="AUTH_SECRET"):
        start.validate_deployment()
    monkeypatch.setattr(settings, "AUTH_SECRET", SecretStr("x" * 32))
    monkeypatch.setattr(settings, "APP_URL", "https://app.example")
    start.validate_deployment()
