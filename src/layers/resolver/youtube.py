import asyncio
from functools import partial

import structlog
import yt_dlp

from src.layers.resolver.factory import ResolvedPodcast, PlatformType

logger = structlog.get_logger()


class YouTubeResolver:
    """Resolve YouTube URLs to podcast metadata using yt-dlp."""

    YDL_OPTS = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "skip_download": True,
        "cookiesfrombrowser": ("edge",),
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
        # Find best audio-only format URL
        audio_url = self._get_audio_url(info)

        return ResolvedPodcast(
            platform=PlatformType.YOUTUBE,
            original_url=url,
            audio_url=audio_url,
            title=info.get("title", "Unknown"),
            description=info.get("description"),
            duration_seconds=float(info.get("duration", 0)),
            published_at=info.get("upload_date"),
            author=info.get("uploader") or info.get("channel"),
            thumbnail_url=info.get("thumbnail"),
            language_hint=info.get("language"),
            extra_metadata={
                "view_count": info.get("view_count"),
                "like_count": info.get("like_count"),
                "channel_id": info.get("channel_id"),
            },
        )

    def _get_audio_url(self, info: dict) -> str:
        """Extract the best audio stream URL from yt-dlp info."""
        formats = info.get("formats", [])
        # Prefer audio-only formats sorted by quality
        audio_formats = [
            f for f in formats
            if f.get("acodec") != "none" and f.get("vcodec") in ("none", None)
        ]
        if audio_formats:
            # Sort by audio bitrate descending
            audio_formats.sort(key=lambda f: f.get("abr") or 0, reverse=True)
            return audio_formats[0]["url"]

        # Fallback: use the URL from the top-level (combined format)
        if "url" in info:
            return info["url"]

        # Last resort: use requested_downloads
        downloads = info.get("requested_downloads", [])
        if downloads:
            return downloads[0].get("url", "")

        raise ValueError("No audio URL found in YouTube video info")
