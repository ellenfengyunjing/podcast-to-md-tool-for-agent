import asyncio
import re
import subprocess
from pathlib import Path

import structlog

logger = structlog.get_logger()


def _get_ffmpeg_path() -> str:
    """Return full path to ffmpeg executable. Uses imageio-ffmpeg as fallback."""
    import shutil

    if shutil.which("ffmpeg"):
        return "ffmpeg"

    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise RuntimeError(
            "ffmpeg not found. Install system ffmpeg or run: pip install imageio-ffmpeg"
        )


async def get_audio_duration(file_path: Path) -> float:
    """Get audio duration in seconds using ffmpeg (no ffprobe needed)."""
    ffmpeg = _get_ffmpeg_path()
    cmd = [ffmpeg, "-i", str(file_path), "-f", "null", "-"]
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: subprocess.run(
        cmd, capture_output=True, text=True
    ))
    # ffmpeg prints duration to stderr even on "error" (no output format)
    stderr = result.stderr
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", stderr)
    if match:
        h, m, s, cs = int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))
        return h * 3600 + m * 60 + s + cs / 100.0

    raise RuntimeError(f"Could not determine audio duration from: {stderr[:500]}")


async def convert_to_wav(input_path: Path, output_path: Path, sample_rate: int = 16000) -> Path:
    """Convert audio file to 16kHz mono WAV using ffmpeg."""
    ffmpeg = _get_ffmpeg_path()
    cmd = [
        ffmpeg, "-y",
        "-i", str(input_path),
        "-ar", str(sample_rate),
        "-ac", "1",
        "-f", "wav",
        str(output_path),
    ]
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: subprocess.run(
        cmd, capture_output=True, text=True
    ))
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {result.stderr[:500]}")

    return output_path


async def split_audio(
    input_path: Path,
    output_dir: Path,
    start_seconds: float,
    duration_seconds: float,
    chunk_index: int,
) -> Path:
    """Extract a segment from an audio file using ffmpeg."""
    ffmpeg = _get_ffmpeg_path()
    output_path = output_dir / f"chunk_{chunk_index:04d}.wav"
    cmd = [
        ffmpeg, "-y",
        "-i", str(input_path),
        "-ss", str(start_seconds),
        "-t", str(duration_seconds),
        "-ar", "16000",
        "-ac", "1",
        "-f", "wav",
        str(output_path),
    ]
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: subprocess.run(
        cmd, capture_output=True, text=True
    ))
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg split failed: {result.stderr[:500]}")

    return output_path
