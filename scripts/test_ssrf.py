import asyncio
import os
import sys

# 调整模块搜索路径到项目根目录
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.api.endpoints.download import _is_allowed_download_url


def check(name: str, platform: str, url: str, expect: bool | None):
    ok = _is_allowed_download_url(platform, url)
    if expect is None:
        print(f"{name}: {url} -> {ok}")
    else:
        print(f"{name}: {url} -> {ok} (expect {expect})")


def main():
    # 允许的公开域名与HTTPS
    # 正向用例（可能需要DNS环境，离线时结果可能为False）
    check("bilibili_https", "bilibili", "https://www.bilibili.com/video/BV1xx", None)
    # 拒绝私网地址
    check("private_ip", "bilibili", "https://127.0.0.1/", False)
    check("localhost", "bilibili", "https://localhost/", False)
    # 拒绝伪造域名
    check("fake_suf", "bilibili", "https://bilibili.com.evil.com/", False)
    # 拒绝非HTTPS
    check("non_https", "bilibili", "http://www.bilibili.com/", False)
    # 拒绝URL中携带用户信息
    check("userinfo", "bilibili", "https://user:pass@www.bilibili.com/", False)


if __name__ == "__main__":
    main()
