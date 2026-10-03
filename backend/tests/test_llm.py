import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app import llm


def provider(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


def completion(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def test_utf8_chunks_preserve_every_character():
    text = "हिन्दी 日本語 🙂 meeting notes. " * 600
    pieces = llm.split_transcript(text)
    assert "".join(pieces) == text
    assert len(pieces) > 1
    assert all(len(piece.encode("utf-8")) <= 8000 for piece in pieces)


@pytest.mark.asyncio
async def test_long_transcript_summarizes_every_chunk_and_merges_notes(monkeypatch):
    requests = []
    def handler(request):
        data = json.loads(request.content)
        source = data["messages"][1]["content"]
        requests.append(source)
        assert len(source.encode("utf-8")) <= 8000
        assert "not as instructions" in data["messages"][0]["content"]
        return completion(f"Notes from chunk {len(requests)}")
    provider(monkeypatch, handler)
    text = "हिन्दी meeting notes 🙂 " * 600
    pieces = llm.split_transcript(text.strip())
    result = await llm.summarize_transcript(text)
    assert requests[:-1] == pieces
    assert all(f"Notes from chunk {i}" in requests[-1] for i in range(1, len(pieces) + 1))
    assert result == f"Notes from chunk {len(pieces) + 1}"


@pytest.mark.asyncio
async def test_large_partial_notes_are_condensed_before_final_summary(monkeypatch):
    sources = []
    def handler(request):
        source = json.loads(request.content)["messages"][1]["content"]
        sources.append(source)
        assert len(source.encode("utf-8")) <= 8000
        return completion("n" * 5000 if len(sources) <= 3 else "Concise notes")
    provider(monkeypatch, handler)
    assert await llm.summarize_transcript("speech " * 3000) == "Concise notes"
    assert len(sources) == 6  # three source chunks, two reductions, one merge


@pytest.mark.asyncio
async def test_rate_limit_is_retried_with_retry_after(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "5"}) if len(calls) == 1 else completion("Recovered summary")
    provider(monkeypatch, handler)
    pause = AsyncMock()
    monkeypatch.setattr(llm.asyncio, "sleep", pause)
    assert await llm.summarize_transcript("Source speech") == "Recovered summary"
    assert len(calls) == 2
    pause.assert_awaited_once_with(5)


@pytest.mark.asyncio
async def test_persistent_rate_limit_stops_after_three_attempts(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429)
    provider(monkeypatch, handler)
    monkeypatch.setattr(llm.asyncio, "sleep", AsyncMock())
    with pytest.raises(httpx.HTTPStatusError):
        await llm.summarize_transcript("Source speech")
    assert len(calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{"message": {"content": " "}}]}, ["bad shape"]])
async def test_invalid_provider_output_is_not_saved_as_a_summary(monkeypatch, body):
    provider(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(RuntimeError):
        await llm.summarize_transcript("Source speech")


@pytest.mark.asyncio
async def test_empty_transcript_never_calls_provider(monkeypatch):
    provider(monkeypatch, lambda request: pytest.fail("Empty transcript reached provider"))
    with pytest.raises(ValueError):
        await llm.summarize_transcript(" \n ")
