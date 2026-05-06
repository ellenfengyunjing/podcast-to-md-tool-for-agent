"""Apple Podcasts resolver.

Apple Podcast URLs look like:

    https://podcasts.apple.com/us/podcast/<slug>/id<itunesId>?i=<episodeId>

There is no public media URL in the page, but Apple publishes an iTunes
Lookup API that maps ``id`` → the original RSS feed URL. From there the
RSS resolver can locate the episode (matching ``trackId`` = ``i``
parameter) and its audio enclosure.

API reference: https://performance-partners.apple.com/search-api
"""
import re
from urllib.parse import parse_qs, urlparse

import feedparser
import httpx
import structlog

from src.layers.resolver.factory import PlatformType, ResolvedPodcast

logger = structlog.get_logger()

_ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"
_ITUNES_ID_PATTERN = re.compile(r"/id(\d+)", re.IGNORECASE)


class ApplePodcastsResolver:
    """Resolve an Apple Podcasts episode URL to its media URL + metadata."""

    async def resolve(self, url: str) -> ResolvedPodcast:
        itunes_id, episode_id = self._parse_ids(url)
        if not itunes_id:
            raise ValueError(f"Could not find itunes id in Apple Podcasts URL: {url}")

        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            feed_url = await self._lookup_feed_url(client, itunes_id)
            if not feed_url:
                raise ValueError(
                    f"iTunes Lookup API did not return a feedUrl for id={itunes_id}"
                )

            feed_bytes = await self._fetch_bytes(client, feed_url)

        feed = feedparser.parse(feed_bytes)
        if not feed.entries:
            raise ValueError(f"RSS feed had no episodes: {feed_url}")

        entry = self._pick_entry(feed.entries, episode_id)
        audio_url = self._get_audio_url(entry)
        if not audio_url:
            raise ValueError(
                f"No audio enclosure for Apple Podcasts episode: {entry.get('title')}"
            )

        return ResolvedPodcast(
            platform=PlatformType.APPLE_PODCASTS,
            original_url=url,
            audio_url=audio_url,
            title=entry.get("title", "Unknown Episode"),
            description=entry.get("summary") or entry.get("description"),
            duration_seconds=self._parse_duration(entry),
            published_at=entry.get("published"),
            author=entry.get("author") or feed.feed.get("author"),
            thumbnail_url=self._get_image(entry, feed),
            language_hint=feed.feed.get("language"),
            extra_metadata={
                "itunes_id": itunes_id,
                "episode_id": episode_id,
                "feed_url": feed_url,
                "feed_title": feed.feed.get("title"),
            },
        )

    # --- helpers ------------------------------------------------------------

    @staticmethod
    def _parse_ids(url: str) -> tuple[str | None, str | None]:
        parsed = urlparse(url)
        match = _ITUNES_ID_PATTERN.search(parsed.path)
        itunes_id = match.group(1) if match else None
        episode_id = parse_qs(parsed.query).get("i", [None])[0]
        return itunes_id, episode_id

    @staticmethod
    async def _lookup_feed_url(client: httpx.AsyncClient, itunes_id: str) -> str | None:
        resp = await client.get(
            _ITUNES_LOOKUP_URL, params={"id": itunes_id, "entity": "podcast"}
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results") or []
        return results[0].get("feedUrl") if results else None

    @staticmethod
    async def _fetch_bytes(client: httpx.AsyncClient, url: str) -> bytes:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content

    @staticmethod
    def _pick_entry(entries: list, episode_id: str | None):
        """Find the entry whose GUID/link/trackId matches ``i=<episode_id>``.

        Falls back to the latest episode when no match is found (or when the
        URL did not include an ``i`` query param).
        """
        if not episode_id:
            return entries[0]

        for entry in entries:
            # Apple's trackId is not always in the feed, but GUID / link often
            # contains it. Do a substring check — cheap and robust.
            candidates = [
                str(entry.get("id", "")),
                str(entry.get("guid", "")),
                str(entry.get("link", "")),
            ]
            if any(episode_id in c for c in candidates):
                return entry

        logger.warning(
            "apple_podcasts_episode_not_matched",
            episode_id=episode_id,
            fallback="latest_episode",
        )
        return entries[0]

    @staticmethod
    def _get_audio_url(entry: dict) -> str | None:
        for enc in entry.get("enclosures", []) or []:
            if str(enc.get("type", "")).startswith("audio/"):
                return enc.get("href")
        for link in entry.get("links", []) or []:
            if str(link.get("type", "")).startswith("audio/"):
                return link.get("href")
        enclosures = entry.get("enclosures", []) or []
        return enclosures[0].get("href") if enclosures else None

    @staticmethod
    def _parse_duration(entry: dict) -> float | None:
        raw = entry.get("itunes_duration")
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            pass
        parts = str(raw).split(":")
        try:
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            return None
        return None

    @staticmethod
    def _get_image(entry: dict, feed) -> str | None:
        image = entry.get("image")
        if isinstance(image, dict):
            return image.get("href")
        feed_image = feed.feed.get("image")
        if isinstance(feed_image, dict):
            return feed_image.get("href")
        return None
