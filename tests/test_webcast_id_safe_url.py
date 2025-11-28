import os
import sys
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from crawlers.douyin.web.utils import WebCastIdFetcher


class _DummyResponse:
    def __init__(self, url: str, status_code: int = 200):
        self.url = url
        self.status_code = status_code

    def raise_for_status(self):
        if not (200 <= self.status_code < 400):
            raise Exception("HTTP error")


class _DummyAsyncClient:
    def __init__(self, *args, **kwargs):
        self._response = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, follow_redirects=True):
        # 返回最终 live 页面 URL 模拟
        return self._response


def test_get_webcast_id_from_live_numeric(monkeypatch):
    # 模拟请求到最终 live 页面
    dummy_client = _DummyAsyncClient()
    dummy_client._response = _DummyResponse("https://live.douyin.com/766545142636")

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: dummy_client)
    import socket
    monkeypatch.setattr(socket, "gethostbyname", lambda h: "1.2.3.4")

    aw = asyncio.run(WebCastIdFetcher.get_webcast_id("https://live.douyin.com/766545142636?foo=bar"))
    assert aw == "766545142636"


def test_get_webcast_id_from_webcast_reflow(monkeypatch):
    # 模拟请求到最终 live 页面
    dummy_client = _DummyAsyncClient()
    dummy_client._response = _DummyResponse("https://live.douyin.com/7318296342189919011")

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: dummy_client)
    import socket
    monkeypatch.setattr(socket, "gethostbyname", lambda h: "1.2.3.4")

    src = "https://webcast.amemv.com/douyin/webcast/reflow/7318296342189919011?from=share&roomId=7318296342189919011"
    aw = asyncio.run(WebCastIdFetcher.get_webcast_id(src))
    assert aw == "7318296342189919011"
