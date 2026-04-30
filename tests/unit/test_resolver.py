from src.layers.resolver.factory import detect_platform, PlatformType


class TestDetectPlatform:
    def test_youtube_watch_url(self):
        url = "https://www.youtube.com/watch?v=abc123"
        assert detect_platform(url) == PlatformType.YOUTUBE

    def test_youtube_short_url(self):
        url = "https://youtu.be/abc123"
        assert detect_platform(url) == PlatformType.YOUTUBE

    def test_youtube_shorts_url(self):
        url = "https://youtube.com/shorts/abc123"
        assert detect_platform(url) == PlatformType.YOUTUBE

    def test_rss_url(self):
        url = "https://feeds.example.com/podcast.xml"
        assert detect_platform(url) == PlatformType.RSS

    def test_rss_feed_url(self):
        url = "https://example.com/feed"
        assert detect_platform(url) == PlatformType.RSS

    def test_generic_url_defaults_to_generic(self):
        url = "https://example.com/some-podcast"
        assert detect_platform(url) == PlatformType.GENERIC

    def test_xiaoyuzhou_url_is_generic(self):
        url = "https://www.xiaoyuzhoufm.com/episode/69f231defbed7ba941222e98"
        assert detect_platform(url) == PlatformType.GENERIC
