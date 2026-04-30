import asyncio
from functools import partial

import feedparser
import httpx
import structlog

from src.layers.resolver.factory import ResolvedPodcast, PlatformType

logger = structlog.get_logger()


class RSSResolver:
    """Resolve RSS feed URLs to podcast episode metadata."""

    async def resolve(self, url: str, episode_index: int = 0) -> ResolvedPodcast:
        feed_content = await self._fetch_feed(url)
        loop = asyncio.get_event_loop()
        feed = await loop.run_in_executor(None, partial(feedparser.parse, feed_content))

        if feed.bozo and not feed.entries:
            raise ValueError(f"Failed to parse RSS feed: {feed.bozo_exception}")

        if not feed.entries:
            raise ValueError("RSS feed has no episodes")

        # Clamp episode index
        episode_index = min(episode_index, len(feed.entries) - 1)
        entry = feed.entries[episode_index]

        audio_url = self._get_audio_url(entry)
        if not audio_url:
            raise ValueError(f"No audio enclosure found in episode: {entry.get('title')}")

        duration = self._parse_duration(entry)

        return ResolvedPodcast(
            platform=PlatformType.RSS,
            original_url=url,
            audio_url=audio_url,
            title=entry.get("title", "Unknown Episode"),
            description=entry.get("summary") or entry.get("description"),
            duration_seconds=duration,
            published_at=entry.get("published"),
            author=entry.get("author") or feed.feed.get("author"),
            thumbnail_url=self._get_image(entry, feed),
            language_hint=feed.feed.get("language"),
            extra_metadata={
                "feed_title": feed.feed.get("title"),
                "episode_count": len(feed.entries),
                "episode_index": episode_index,
            },
        )

    async def _fetch_feed(self, url: str) -> str:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    def _get_audio_url(self, entry: dict) -> str | None:
        # Check enclosures
        enclosures = entry.get("enclosures", [])
        for enc in enclosures:
            if enc.get("type", "").startswith("audio/"):
                return enc.get("href")

        # Check links
        links = entry.get("links", [])
        for link in links:
            if link.get("type", "").startswith("audio/"):
                return link.get("href")

        # Fallback: first enclosure regardless of type
        if enclosures:
            return enclosures[0].get("href")

        return None

    def _parse_duration(self, entry: dict) -> float | None:
        # itunes:duration can be HH:MM:SS, MM:SS, or seconds
        duration_str = entry.get("itunes_duration")
        if not duration_str:
            return None

        try:
            # Pure number = seconds
            return float(duration_str)
        except ValueError:
            pass

        # Parse HH:MM:SS or MM:SS
        parts = duration_str.split(":")
        try:
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            pass

        return None

    def _get_image(self, entry: dict, feed) -> str | None:
        # Episode-level image
        image = entry.get("image")
        if image and isinstance(image, dict):
            return image.get("href")

        # Feed-level image
        feed_image = feed.feed.get("image")
        if feed_image and isinstance(feed_image, dict):
            return feed_image.get("href")

        return None
