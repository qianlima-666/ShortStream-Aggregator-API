import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.web.views.ViewsUtils import ViewsUtils


def test_find_url_basic():
    s = "Check https://live.douyin.com/123456 and https://v.douyin.com/e4J8Q7A/ now"
    urls = ViewsUtils.find_url(s)
    assert "https://live.douyin.com/123456" in urls
    assert "https://v.douyin.com/e4J8Q7A/" in urls


def test_find_url_handles_percent_encoding():
    s = "Go https://example.com/path?x=%20%2F%3A%5B%5D"
    urls = ViewsUtils.find_url(s)
    assert urls == ["https://example.com/path?x=%20%2F%3A%5B%5D"]


def test_find_url_not_match_invalid():
    s = "invalid httpz://site.com and just text"
    urls = ViewsUtils.find_url(s)
    assert urls == []

