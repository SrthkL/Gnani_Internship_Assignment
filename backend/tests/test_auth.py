from datetime import timedelta
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import pytest_asyncio
from fastapi import Response
from sqlalchemy import func, select, text
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import main
from app import auth, guests, tasks
from app.config import settings
from app.db import Base
from app.migrations import initialize_schema
from app.models import BrowserSession, Upload, User


@pytest_asyncio.fixture
async def api(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await initialize_schema(connection)
    async def dependency():
        async with sessions() as db:
            yield db
    main.app.dependency_overrides[main.get_db] = dependency
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path / "persistent"))
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "APP_URL", "http://test")
    monkeypatch.setattr(tasks, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(guests.tempfile, "tempdir", str(tmp_path))
    clients = []
    async def client(user_id=None):
        browser = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test", headers={"Origin": "http://test"})
        clients.append(browser)
        if user_id:
            response = Response()
            async with sessions() as db:
                db.add(User(id=user_id, google_sub=user_id, email=f"{user_id}@example.test", name=user_id))
                await auth.new_session(db, response, user_id)
            browser.cookies.extract_cookies(httpx.Response(200, headers={"set-cookie": response.headers["set-cookie"]}, request=httpx.Request("GET", "http://test")))
        else:
            assert (await browser.get("/auth/me")).status_code == 200
        return browser
    try:
        yield client, sessions
    finally:
        for browser in clients:
            await browser.aclose()
        for job in guests.guest_jobs.values():
            job.expires_at = auth.now()
            job.status = "failed"
        await guests.cleanup_guests()
        main.app.dependency_overrides.clear()
        await engine.dispose()


async def upload(browser):
    return await browser.post("/uploads", files={"file": ("speech.wav", b"audio", "audio/wav")})


@pytest.mark.asyncio
async def test_guest_has_one_recording_no_history_and_no_persistent_results(api, monkeypatch):
    client, sessions = api
    browser = await client()
    other = await client()
    response = await upload(browser)
    assert response.status_code == 201
    recording_id = response.json()["id"]
    job = guests.guest_jobs[recording_id]
    temporary_directory = Path(job.directory)
    assert (await upload(browser)).status_code == 403
    assert (await browser.get("/uploads")).status_code == 401
    assert (await other.get(f"/uploads/{recording_id}")).status_code == 404
    assert (await other.post(f"/uploads/{recording_id}/transcribe")).status_code == 404
    async def transcribe(path, on_progress):
        assert Path(path).is_file()
        await on_progress(50)
        assert (await browser.get(f"/uploads/{recording_id}")).json()["progress"] == 50
        await on_progress(100)
        return "Temporary guest speech"
    monkeypatch.setattr(guests, "transcribe_audio", transcribe)
    monkeypatch.setattr(guests, "summarize_transcript", AsyncMock(return_value="Temporary summary"))
    assert (await browser.post(f"/uploads/{recording_id}/transcribe")).status_code == 202
    result = (await browser.get(f"/uploads/{recording_id}")).json()
    assert result["transcript"] == "Temporary guest speech"
    assert result["summary"] == "Temporary summary"
    assert result["progress"] == 100
    assert not temporary_directory.exists()
    assert not Path(settings.STORAGE_DIR).exists()
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Upload)) == 0
    # Reloading retains the same guest result, not a fresh allowance.
    status = (await browser.get("/auth/me")).json()
    assert status["guest_used"] and status["guest_upload"]["id"] == recording_id
    # A genuinely separate browser session gets its own allowance.
    assert (await upload(other)).status_code == 201


@pytest.mark.asyncio
async def test_account_history_details_and_processing_are_owner_only(api, monkeypatch):
    client, sessions = api
    owner, other, guest = await client("alice"), await client("bob"), await client()
    response = await upload(owner)
    assert response.status_code == 201
    recording_id = response.json()["id"]
    async with sessions() as db:
        db.add(Upload(id="legacy", filename="old.wav", storage_key="old.wav", status="completed", transcript="Old public demo"))
        await db.commit()
    for browser in (other, guest):
        assert (await browser.get(f"/uploads/{recording_id}")).status_code == 404
        assert (await browser.post(f"/uploads/{recording_id}/transcribe")).status_code == 404
    assert (await owner.get("/uploads/legacy")).status_code == 404
    assert (await other.get("/uploads/legacy")).status_code == 404
    assert (await other.get("/uploads")).json() == []
    monkeypatch.setattr(tasks, "transcribe_audio", AsyncMock(return_value="Private transcript"))
    monkeypatch.setattr(tasks, "summarize_transcript", AsyncMock(return_value="Private summary"))
    assert (await owner.post(f"/uploads/{recording_id}/transcribe")).status_code == 202
    history = await owner.get("/uploads")
    assert history.headers["cache-control"] == "no-store"
    assert [row["id"] for row in history.json()] == [recording_id]
    assert history.json()[0]["transcript"] == "Private transcript"
    async with sessions() as db:
        saved = await db.get(Upload, recording_id)
        assert saved.user_id == "alice" and saved.summary == "Private summary"


@pytest.mark.asyncio
async def test_logout_revokes_cookie_even_when_replayed(api):
    client, sessions = api
    browser = await client("alice")
    cookie = browser.cookies.get(auth.COOKIE)
    assert (await browser.post("/auth/logout")).status_code == 200
    browser.cookies.set(auth.COOKIE, cookie)
    assert (await browser.get("/uploads")).status_code == 401
    async with sessions() as db:
        assert await db.get(BrowserSession, auth.token_hash(cookie)) is None


@pytest.mark.asyncio
async def test_expired_session_cannot_read_history(api):
    client, sessions = api
    browser = await client("alice")
    async with sessions() as db:
        session = await db.get(BrowserSession, auth.token_hash(browser.cookies.get(auth.COOKIE)))
        session.expires_at = auth.now() - timedelta(seconds=1)
        await db.commit()
    assert (await browser.get("/uploads")).status_code == 401
    result = (await browser.get("/auth/me")).json()
    assert result["user"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["https://attacker.example", "null", ""])
async def test_cross_site_writes_rejected(api, origin):
    client, _ = api
    browser = await client("alice")
    browser.headers["Origin"] = origin
    assert (await upload(browser)).status_code == 403
    assert (await browser.post("/auth/logout")).status_code == 403


@pytest.mark.asyncio
async def test_guest_expiry_removes_audio_and_transcript_but_not_quota(api):
    client, _ = api
    browser = await client()
    recording_id = (await upload(browser)).json()["id"]
    job = guests.guest_jobs[recording_id]
    directory = Path(job.directory)
    job.transcript = "Temporary"
    job.expires_at = auth.now() - timedelta(seconds=1)
    await guests.cleanup_guests()
    assert recording_id not in guests.guest_jobs and not directory.exists()
    assert (await browser.get(f"/uploads/{recording_id}")).status_code == 404
    assert (await upload(browser)).status_code == 403


@pytest.mark.asyncio
async def test_invalid_upload_does_not_use_guest_allowance(api):
    client, _ = api
    browser = await client()
    assert (await browser.post("/uploads", files={"file": ("notes.txt", b"not audio")})).status_code == 415
    assert (await browser.post("/uploads", files={"file": ("empty.wav", b"")})).status_code == 413
    assert (await upload(browser)).status_code == 201


@pytest.mark.asyncio
async def test_parallel_guest_uploads_cannot_bypass_one_file_limit(api):
    client, _ = api
    browser = await client()
    responses = await asyncio.gather(upload(browser), upload(browser))
    assert sorted(response.status_code for response in responses) == [201, 403]


@pytest.mark.asyncio
async def test_google_callback_requires_real_oauth_state(api):
    client, _ = api
    browser = await client()
    response = await browser.get("/auth/google/callback?code=forged&state=forged")
    assert response.status_code == 303
    assert "auth_error=google" in response.headers["location"]
    assert (await browser.get("/auth/me")).json()["user"] is None


@pytest.mark.asyncio
async def test_google_redirect_uses_configured_origin_state_nonce_and_pkce(api, monkeypatch):
    client, _ = api
    browser = await client()
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "test-google-client")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", SecretStr("test-secret"))
    monkeypatch.setattr(auth.oauth.google, "client_id", "test-google-client")
    monkeypatch.setattr(auth.oauth.google, "load_server_metadata", AsyncMock(return_value={"authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth"}))
    response = await browser.get("/auth/google")
    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert location.hostname == "accounts.google.com"
    query = parse_qs(location.query)
    assert query["redirect_uri"] == ["http://test/api/auth/google/callback"]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] and query["nonce"] and query["code_challenge"]
    assert "httponly" in response.headers["set-cookie"].lower()


@pytest.mark.asyncio
async def test_account_cookie_is_secure_in_production_and_not_a_bearer_identity(api, monkeypatch):
    _, sessions = api
    monkeypatch.setattr(settings, "APP_ENV", "production")
    async with sessions() as db:
        response = Response()
        session = await auth.new_session(db, response)
        cookie = response.headers["set-cookie"]
        assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
        assert "Max-Age" not in cookie
        assert session.token_hash not in cookie


@pytest.mark.asyncio
@pytest.mark.parametrize("verified", [True, False])
async def test_validated_google_identity_rotates_session_and_requires_verified_email(api, monkeypatch, verified):
    client, sessions = api
    browser = await client()
    old_cookie = browser.cookies.get(auth.COOKIE)
    # Isolate the account/session mapping after Authlib's OIDC validation.
    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", AsyncMock(return_value={"userinfo": {"sub": "google-person", "email": "person@example.test", "name": "Person", "email_verified": verified}}))
    response = await browser.get("/auth/google/callback")
    assert response.status_code == 303
    me = (await browser.get("/auth/me")).json()
    if verified:
        assert me["user"]["email"] == "person@example.test"
        assert browser.cookies.get(auth.COOKIE) != old_cookie
        async with sessions() as db:
            assert await db.get(BrowserSession, auth.token_hash(old_cookie)) is None
        # Subsequent login resolves the same account, not a duplicate.
        await browser.get("/auth/google/callback")
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(User)) == 1
    else:
        assert me["user"] is None and "auth_error" in response.headers["location"]


@pytest.mark.asyncio
async def test_ownership_migration_preserves_old_rows_and_is_repeatable(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE uploads (id VARCHAR PRIMARY KEY, filename VARCHAR NOT NULL, storage_key VARCHAR NOT NULL, status VARCHAR NOT NULL, progress INTEGER NOT NULL, transcript TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, summary TEXT, error_message TEXT)"))
            await connection.execute(text("INSERT INTO uploads (id,filename,storage_key,status,progress,transcript) VALUES ('old','old.wav','audio/old.wav','completed',100,'Keep this result')"))
            await initialize_schema(connection)
            await initialize_schema(connection)
            row = (await connection.execute(select(Upload))).mappings().one()
            assert row["user_id"] is None and row["transcript"] == "Keep this result"
    finally:
        await engine.dispose()
