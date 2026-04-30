import asyncio
from functools import partial
from pathlib import Path

import httpx
import structlog
import yt_dlp

from src.layers.resolver.factory import ResolvedPodcast, PlatformType
from src.utils.audio_utils import convert_to_wav, get_audio_duration, _get_ffmpeg_path

logger = structlog.get_logger()


class ExtractedAudio:
    def __init__(self, file_path: Path, duration_seconds: float, file_size_bytes: int):
        self.file_path = file_path
        self.duration_seconds = duration_seconds
        self.file_size_bytes = file_size_bytes


class AudioExtractor:
    """Download and convert podcast audio to 16kHz mono WAV."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    async def extract(self, resolved: ResolvedPodcast, job_id: str) -> ExtractedAudio:
        job_dir = self.data_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        if resolved.platform == PlatformType.YOUTUBE:
            raw_path = await self._download_youtube(resolved.original_url, job_dir)
        else:
            # GENERIC and RSS both have a direct audio_url
            raw_path = await self._download_http(resolved.audio_url, job_dir)

        # Convert to 16kHz mono WAV
        wav_path = job_dir / "audio.wav"
        await convert_to_wav(raw_path, wav_path)

        # Clean up raw download
        if raw_path != wav_path and raw_path.exists():
            raw_path.unlink()

        duration = await get_audio_duration(wav_path)
        file_size = wav_path.stat().st_size

        logger.info("audio_extracted", job_id=job_id, duration=duration, size_mb=file_size / 1e6)
        return ExtractedAudio(
            file_path=wav_path,
            duration_seconds=duration,
            file_size_bytes=file_size,
        )

    async def _download_youtube(self, url: str, output_dir: Path) -> Path:
        output_template = str(output_dir / "raw_audio.%(ext)s")
        ffmpeg_path = _get_ffmpeg_path()
        ffmpeg_dir = str(Path(ffmpeg_path).parent)

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "quiet": True,
            "no_warnings": True,
            "ffmpeg_location": ffmpeg_dir,
            "cookiesfrombrowser": ("edge",),
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
            }],
        }

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, partial(self._ydl_download, url, ydl_opts))

        # Find the downloaded file
        wav_files = list(output_dir.glob("raw_audio.*"))
        if not wav_files:
            raise RuntimeError("yt-dlp download produced no output file")
        return wav_files[0]

    def _ydl_download(self, url: str, opts: dict):
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

    async def _download_http(self, audio_url: str, output_dir: Path) -> Path:
        output_path = output_dir / "raw_audio.download"
        async with httpx.AsyncClient(follow_redirects=True, timeout=300.0) as client:
            async with client.stream("GET", audio_url) as response:
                response.raise_for_status()
                with open(output_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        f.write(chunk)

        logger.info("http_download_complete", path=str(output_path))
        return output_path
