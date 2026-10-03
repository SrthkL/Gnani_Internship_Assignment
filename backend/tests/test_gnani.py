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

    progress = []

    async def record_progress(percent):
        progress.append(percent)

    transcript = await gnani.transcribe_audio(
        "unused-source.wav", on_progress=record_progress,
    )

    assert transcript == (
        "First part of the recording.\n"
        "Second part of the recording."
    )
    assert not directory.exists()
    assert progress == [50, 100]


@pytest.mark.asyncio
async def test_transcribe_audio_cleans_up_on_failure(
    monkeypatch,
    tmp_path,
):
    directory = tmp_path / "failed-job"
    directory.mkdir()

    async def fake_prepare_audio(audio_path):
        return str(directory), ["first-chunk.wav", "failed-chunk.wav"]

    async def fake_create_job(audio_path):
        if audio_path == "failed-chunk.wav":
            raise RuntimeError("Provider unavailable")
        return "first-job"

    async def fake_job_action(job_id):
        pass

    async def fake_fetch_transcript(job_id):
        return "First chunk completed."

    progress = []

    async def record_progress(percent):
        progress.append(percent)

    monkeypatch.setattr(gnani, "prepare_audio", fake_prepare_audio)
    monkeypatch.setattr(gnani, "create_job", fake_create_job)
    monkeypatch.setattr(gnani, "start_job", fake_job_action)
    monkeypatch.setattr(gnani, "wait_for_completion", fake_job_action)
    monkeypatch.setattr(gnani, "fetch_transcript", fake_fetch_transcript)

    with pytest.raises(RuntimeError, match="Provider unavailable"):
        await gnani.transcribe_audio("unused-source.wav", on_progress=record_progress)

    assert not directory.exists()
    assert progress == [50]
