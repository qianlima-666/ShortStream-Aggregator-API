import os
import sys
import pytest

# 保证测试可导入项目包
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from crawlers.douyin.web.utils import SecUserIdFetcher


class _DummyResponse:
    def __init__(self, url: str, status_code: int = 200):
        self.url = url
        self.status_code = status_code


class _DummyAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, follow_redirects=True):
        return self._response


def test_shortlink_hostname_selects_redirect_pattern(monkeypatch):
    # 输入短链域名，期望使用 _REDIRECT_URL_PATTERN（sec_uid）
    dummy_client = _DummyAsyncClient()
    dummy_client._response = _DummyResponse("https://www.douyin.com/?sec_uid=abc123")

    # 替换 httpx.AsyncClient
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: dummy_client)

    import asyncio
    sec_uid = asyncio.run(SecUserIdFetcher.get_sec_user_id("https://v.douyin.com/XXXX"))
    assert sec_uid == "abc123"


def test_non_shortlink_with_substring_uses_user_pattern(monkeypatch):
    # 原始 URL 中包含 "v.douyin.com" 子串但主机并非该域，应选择 _DOUYIN_URL_PATTERN（user/<sec_uid>）
    dummy_client = _DummyAsyncClient()
    dummy_client._response = _DummyResponse("https://www.douyin.com/user/xyz987")

    # 替换 httpx.AsyncClient
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: dummy_client)

    import asyncio
    sec_uid = asyncio.run(SecUserIdFetcher.get_sec_user_id("https://example.com/?q=v.douyin.com"))
    assert sec_uid == "xyz987"
