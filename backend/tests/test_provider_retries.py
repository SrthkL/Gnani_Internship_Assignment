import httpx
import pytest

from app import gnani


@pytest.mark.asyncio
async def test_rate_limited_upload_rewinds_audio_and_honors_retry_after(monkeypatch, tmp_path):
    audio = tmp_path / "chunk.wav"
    audio.write_bytes(b"unique-audio-content")
    bodies = []
    delays = []

    def handler(request):
        bodies.append(request.content)
        if len(bodies) == 1:
            return httpx.Response(429, headers={"Retry-After": "17"})
        return httpx.Response(201, json={"job_id": "test-job"})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        gnani.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr(gnani.settings, "GNANI_API_KEY", "test-key")

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(gnani.asyncio, "sleep", sleep)

    assert await gnani.create_job(str(audio)) == "test-job"
    assert len(bodies) == 2
    assert all(b"unique-audio-content" in body for body in bodies)
    assert delays == [17]


@pytest.mark.asyncio
async def test_start_retry_accepts_job_that_was_already_started(monkeypatch):
    methods = []

    def handler(request):
        methods.append(request.method)
        if len(methods) == 1:
            return httpx.Response(503)
        if request.method == "POST":
            return httpx.Response(409)
        return httpx.Response(200, json={"status": "IN_PROGRESS"})

    async def sleep(delay):
        pass

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        gnani.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr(gnani.asyncio, "sleep", sleep)

    await gnani.start_job("test-job")
    assert methods == ["POST", "POST", "GET"]


@pytest.mark.asyncio
async def test_persistent_rate_limit_stops_after_four_attempts(monkeypatch):
    requests = []
    delays = []

    def handler(request):
        requests.append(request)
        return httpx.Response(429)

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(gnani.asyncio, "sleep", sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError) as failure:
            await gnani._request_with_retry(client, "GET", "https://example.test/job")

    assert failure.value.response.status_code == 429
    assert len(requests) == 4
    assert delays == [10, 20, 40]
