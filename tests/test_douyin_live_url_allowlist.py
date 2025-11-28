import os
import sys
import pytest

# 将项目根目录加入搜索路径，确保本地运行测试可导入包
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from crawlers.douyin.web.utils import is_allowed_douyin_live_url, WebCastIdFetcher
from crawlers.utils.api_exceptions import APINotFoundError


def test_is_allowed_douyin_live_url_true_live_douyin_https():
    url = "https://live.douyin.com/123456789"
    assert is_allowed_douyin_live_url(url) is True


def test_is_allowed_douyin_live_url_true_webcast_amemv_https():
    url = "https://webcast.amemv.com/douyin/webcast/reflow/7318296342189919011"
    assert is_allowed_douyin_live_url(url) is True


def test_is_allowed_douyin_live_url_false_http():
    url = "http://live.douyin.com/123456789"
    assert is_allowed_douyin_live_url(url) is False


def test_is_allowed_douyin_live_url_false_other_host():
    url = "https://example.com/path"
    assert is_allowed_douyin_live_url(url) is False


def test_get_webcast_id_rejects_non_allowed_domain():
    import asyncio
    with pytest.raises(APINotFoundError):
        asyncio.run(WebCastIdFetcher.get_webcast_id("https://example.com/anything"))
