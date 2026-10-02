from pathlib import Path

import pytest

from app import gnani


@pytest.mark.asyncio
async def test_transcribe_audio_combines_chunks_and_cleans_up(
    monkeypatch,
    tmp_path,
):
    directory = tmp_path / "chunks"
    directory.mkdir()

    chunks = [
        directory / "chunk-000000.wav",
        directory / "chunk-000001.wav",
    ]

    for chunk in chunks:
        chunk.write_bytes(b"test placeholder")

    async def fake_prepare_audio(audio_path):
        return str(directory), [str(chunk) for chunk in chunks]

    async def fake_create_job(audio_path):
        return Path(audio_path).name

    async def fake_job_action(job_id):
        pass

    async def fake_fetch_transcript(job_id):
        return {
            "chunk-000000.wav": "First part of the recording.",
            "chunk-000001.wav": "Second part of the recording.",
        }[job_id]

    # Replace external processing with predictable test functions.
    monkeypatch.setattr(gnani, "prepare_audio", fake_prepare_audio)
    monkeypatch.setattr(gnani, "create_job", fake_create_job)
    monkeypatch.setattr(gnani, "start_job", fake_job_action)
    monkeypatch.setattr(gnani, "wait_for_completion", fake_job_action)
    monkeypatch.setattr(gnani, "fetch_transcript", fake_fetch_transcript)

    transcript = await gnani.transcribe_audio("unused-source.wav")

    assert transcript == (
        "First part of the recording.\n"
        "Second part of the recording."
    )
    assert not directory.exists()


@pytest.mark.asyncio
async def test_transcribe_audio_cleans_up_on_failure(
    monkeypatch,
    tmp_path,
):
    directory = tmp_path / "failed-job"
    directory.mkdir()

    async def fake_prepare_audio(audio_path):
        return str(directory), ["unused-chunk.wav"]

    async def fake_create_job(audio_path):
        raise RuntimeError("Provider unavailable")

    monkeypatch.setattr(gnani, "prepare_audio", fake_prepare_audio)
    monkeypatch.setattr(gnani, "create_job", fake_create_job)

    with pytest.raises(RuntimeError, match="Provider unavailable"):
        await gnani.transcribe_audio("unused-source.wav")

    assert not directory.exists()