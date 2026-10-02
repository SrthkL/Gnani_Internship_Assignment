import shutil
import tempfile
import wave

import pytest

from app.audio import prepare_audio
from app.config import settings


@pytest.mark.asyncio
async def test_prepare_audio_normalizes_and_splits(monkeypatch, tmp_path):
    source = tmp_path / "recording.wav"

    # Generate five seconds of stereo audio at 8 kHz.
    with wave.open(str(source), "wb") as recording:
        recording.setnchannels(2)
        recording.setsampwidth(2)
        recording.setframerate(8000)
        recording.writeframes(b"\x00" * (8000 * 5 * 2 * 2))

    # Use short chunks and keep temporary files inside the test directory.
    monkeypatch.setattr(settings, "AUDIO_CHUNK_SECONDS", 2)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    directory, chunks = await prepare_audio(str(source))

    try:
        assert len(chunks) == 3

        total_duration = 0

        for chunk in chunks:
            with wave.open(chunk, "rb") as recording:
                assert recording.getnchannels() == 1
                assert recording.getframerate() == 16000
                assert recording.getsampwidth() == 2

                total_duration += (
                    recording.getnframes() / recording.getframerate()
                )

        assert total_duration == pytest.approx(5, abs=0.01)
    finally:
        shutil.rmtree(directory, ignore_errors=True)