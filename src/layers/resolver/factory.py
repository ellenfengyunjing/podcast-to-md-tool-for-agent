"""Platform detection and a unified ``resolve_podcast`` entry point.

Supported platforms (in priority order):
1. Apple Podcasts — ``podcasts.apple.com/.../id<itunesId>?i=<episodeId>``
   Resolved via the iTunes Lookup API to find the episode's RSS feed,
   then the RSS resolver pulls the episode audio URL.
2. Xiaoyuzhou FM (小宇宙) — ``www.xiaoyuzhoufm.com/episode/<id>``
   Resolved via yt-dlp's generic extractor (handles 小宇宙 shares correctly).
3. YouTube — ``youtube.com/watch``, ``youtu.be/``, ``youtube.com/shorts/``
4. RSS / Atom feeds — URLs ending in ``.xml``, ``.rss``, ``/feed``, ``/rss``
5. Generic — anything else yt-dlp's generic extractor can handle, including
   direct audio URLs (MP3/M4A/WAV/OGG).
"""
import re
from enum import Enum

from pydantic import BaseModel


class PlatformType(str, Enum):
    APPLE_PODCASTS = "apple_podcasts"
    XIAOYUZHOU = "xiaoyuzhou"
    YOUTUBE = "youtube"
    RSS = "rss"
    GENERIC = "generic"


class ResolvedPodcast(BaseModel):
    platform: PlatformType
    original_url: str
    audio_url: str
    title: str
    description: str | None = None
    duration_seconds: float | None = None
    published_at: str | None = None
    author: str | None = None
    thumbnail_url: str | None = None
    language_hint: str | None = None
    extra_metadata: dict = {}


_APPLE_PODCASTS_PATTERN = re.compile(
    r"podcasts\.apple\.com/[^/]+/podcast/[^/]*/id\d+", re.IGNORECASE
)
_XIAOYUZHOU_PATTERN = re.compile(
    r"(?:www\.)?xiaoyuzhoufm\.com/episode/", re.IGNORECASE
)
_YOUTUBE_PATTERN = re.compile(
    r"(youtube\.com/watch|youtu\.be/|youtube\.com/shorts/)", re.IGNORECASE
)
_RSS_PATTERN = re.compile(
    r"\.(xml|rss)(\?|$)|/feed(\?|/|$)|/rss(\?|/|$)", re.IGNORECASE
)


def detect_platform(url: str) -> PlatformType:
    if _APPLE_PODCASTS_PATTERN.search(url):
        return PlatformType.APPLE_PODCASTS
    if _XIAOYUZHOU_PATTERN.search(url):
        return PlatformType.XIAOYUZHOU
    if _YOUTUBE_PATTERN.search(url):
        return PlatformType.YOUTUBE
    if _RSS_PATTERN.search(url):
        return PlatformType.RSS
    return PlatformType.GENERIC


async def resolve_podcast(url: str) -> ResolvedPodcast:
    """Resolve any supported podcast URL into a ``ResolvedPodcast``."""
    platform = detect_platform(url)

    if platform == PlatformType.APPLE_PODCASTS:
        from src.layers.resolver.apple import ApplePodcastsResolver
        return await ApplePodcastsResolver().resolve(url)
    if platform == PlatformType.YOUTUBE:
        from src.layers.resolver.youtube import YouTubeResolver
        return await YouTubeResolver().resolve(url)
    if platform == PlatformType.RSS:
        from src.layers.resolver.rss import RSSResolver
        return await RSSResolver().resolve(url)

    # Xiaoyuzhou + everything else goes through yt-dlp's generic extractor
    from src.layers.resolver.generic import GenericResolver
    resolved = await GenericResolver().resolve(url)
    if platform == PlatformType.XIAOYUZHOU:
        # Override the platform label for nicer reporting
        resolved = resolved.model_copy(update={"platform": PlatformType.XIAOYUZHOU})
    return resolved
