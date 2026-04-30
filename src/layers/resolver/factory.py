import re

from pydantic import BaseModel
from enum import Enum


class PlatformType(str, Enum):
    YOUTUBE = "youtube"
    RSS = "rss"
    GENERIC = "generic"  # Any URL that yt-dlp can handle via generic extractor


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


_YOUTUBE_PATTERN = re.compile(
    r"(youtube\.com/watch|youtu\.be/|youtube\.com/shorts/)", re.IGNORECASE
)

_RSS_PATTERN = re.compile(
    r"\.(xml|rss)(\?|$)|/feed(\?|/|$)|/rss(\?|/|$)", re.IGNORECASE
)


def detect_platform(url: str) -> PlatformType:
    if _YOUTUBE_PATTERN.search(url):
        return PlatformType.YOUTUBE
    if _RSS_PATTERN.search(url):
        return PlatformType.RSS
    return PlatformType.GENERIC
