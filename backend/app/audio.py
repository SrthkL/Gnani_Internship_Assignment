import asyncio
import shutil
import tempfile
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from app.config import settings


async def prepare_audio(audio_path: str) -> tuple[str, list[str]]:
    """Convert a recording into ordered, provider-compatible WAV chunks."""

    chunk_seconds = settings.AUDIO_CHUNK_SECONDS

    if not 1 <= chunk_seconds <= 240:
        raise ValueError("Audio chunk duration must be between 1 and 240 seconds")

    # Use a separate temporary folder for each recording.
    directory = tempfile.mkdtemp(prefix="gnani-audio-")
    output_pattern = str(Path(directory) / "chunk-%06d.wav")
    process = None

    try:
        process = await asyncio.create_subprocess_exec(
            get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel", "error",
            "-nostdin",
            "-i", str(Path(audio_path).resolve()),
            "-map", "0:a:0",
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-c:a", "pcm_s16le",
            "-f", "segment",
            "-segment_time", str(chunk_seconds),
            "-reset_timestamps", "1",
            output_pattern,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )

        # Stop waiting if conversion takes more than five minutes.
        await asyncio.wait_for(process.communicate(), timeout=300)

        if process.returncode != 0:
            raise ValueError("Audio could not be decoded")

        # Zero-padded filenames preserve the recording's sequence.
        chunks = sorted(Path(directory).glob("chunk-*.wav"))

        if not chunks:
            raise ValueError("Audio produced no usable chunks")

        for chunk in chunks:
            if chunk.stat().st_size > 10 * 1024 * 1024:
                raise ValueError("Audio chunk exceeds the provider size limit")

        return directory, [str(chunk) for chunk in chunks]

    except BaseException:
        # Clean up on failure, timeout, or request cancellation.
        try:
            if process is not None and process.returncode is None:
                process.kill()
                await process.communicate()
        finally:
            shutil.rmtree(directory, ignore_errors=True)
        raise