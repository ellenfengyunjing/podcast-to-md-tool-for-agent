import asyncio
from functools import partial

import structlog
import yt_dlp

from src.layers.resolver.factory import ResolvedPodcast, PlatformType

logger = structlog.get_logger()


class GenericResolver:
    """Resolve podcast URLs using yt-dlp's generic extractor (works for Xiaoyuzhou FM, etc.)."""

    YDL_OPTS = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    async def resolve(self, url: str) -> ResolvedPodcast:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, partial(self._extract_info, url))
        return self._build_result(url, info)

    def _extract_info(self, url: str) -> dict:
        with yt_dlp.YoutubeDL(self.YDL_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                raise ValueError(f"Failed to extract info from: {url}")
            return info

    def _build_result(self, url: str, info: dict) -> ResolvedPodcast:
        audio_url = info.get("url", "")

        # Try to get duration from formats if not in top-level
        duration = info.get("duration")
        if not duration:
            formats = info.get("formats", [])
            for fmt in formats:
                if fmt.get("duration"):
                    duration = fmt["duration"]
                    break

        return ResolvedPodcast(
            platform=PlatformType.GENERIC,
            original_url=url,
            audio_url=audio_url,
            title=info.get("title", "Unknown"),
            description=info.get("description"),
            duration_seconds=float(duration) if duration else None,
            published_at=info.get("upload_date"),
            author=info.get("uploader") or info.get("channel"),
            thumbnail_url=info.get("thumbnail"),
            language_hint=None,
            extra_metadata={
                "ext": info.get("ext"),
                "filesize": info.get("filesize"),
            },
        )
