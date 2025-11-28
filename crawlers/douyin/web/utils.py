import asyncio
import json
import os
import random
import re
import time
from pathlib import Path
from typing import Union
from urllib.parse import quote, urlparse

# import execjs
import httpx
import qrcode
import yaml

from crawlers.douyin.web.abogus import ABogus as AB
from crawlers.douyin.web.xbogus import XBogus as XB
from crawlers.utils.api_exceptions import (
    APIConnectionError,
    APINotFoundError,
    APIResponseError,
    APIUnauthorizedError,
    APIUnavailableError,
)
from crawlers.utils.logger import logger
from crawlers.utils.utils import (
    extract_valid_urls,
    gen_random_str,
    get_timestamp,
    split_filename,
)

def is_allowed_douyin_live_url(url: str) -> bool:
    """
    检查输入 URL 是否属于允许的抖音直播域名，用于防止服务端请求伪造（SSRF）。

    仅允许 `https` 且主机名为 `live.douyin.com` 或 `webcast.amemv.com` 的链接，并排除IP地址、私有/本地地址以防SSRF攻击。

    Args:
        url (str): 待校验的 URL

    Returns:
        bool: 当且仅当 URL 满足安全白名单策略时返回 True
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            return False
        host = parsed.hostname
        if not host:
            return False
        normalized_host = host.rstrip('.').lower()
        allowed_hosts = {"live.douyin.com", "webcast.amemv.com"}
        if normalized_host not in allowed_hosts:
            return False
        import socket
        import ipaddress
        try:
            addr = socket.gethostbyname(normalized_host)
            ip_obj = ipaddress.ip_address(addr)
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_reserved
                or ip_obj.is_link_local
                or ip_obj.is_multicast
            ):
                return False
        except Exception:
            return False
        return True
    except Exception:
        return False

# 配置文件路径
# Read the configuration file
path = os.path.abspath(os.path.dirname(__file__))

# 读取配置文件（统一从项目根的 config 目录读取）
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_cfg = os.path.join(_root, "config", "douyin_web.yaml")
with open(_cfg, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)
_gcfg = os.path.join(_root, "config", "config.yaml")
try:
    with open(_gcfg, "r", encoding="utf-8") as gf:
        global_config = yaml.safe_load(gf)
except Exception:
    global_config = {}


class TokenManager:
    douyin_manager = config.get("TokenManager").get("douyin")
    token_conf = douyin_manager.get("msToken", None)
    ttwid_conf = douyin_manager.get("ttwid", None)
    proxies_conf = douyin_manager.get("proxies", None)
    proxies = {
        "http://": proxies_conf.get("http", None),
        "https://": proxies_conf.get("https", None),
    }

    @classmethod
    def gen_real_msToken(cls) -> str:
        """
        生成真实的msToken,当出现错误时返回虚假的值
        (Generate a real msToken and return a false value when an error occurs)
        """
        try:
            sec = bool(global_config.get("API", {}).get("Security", {}).get("StrictValidation", True))
        except Exception:
            sec = True
        if not sec:
            return cls.gen_false_msToken()
        payload = json.dumps(
            {
                "magic": cls.token_conf["magic"],
                "version": cls.token_conf["version"],
                "dataType": cls.token_conf["dataType"],
                "strData": cls.token_conf["strData"],
                "tspFromClient": get_timestamp(),
            }
        )
        headers = {
            "User-Agent": cls.token_conf["User-Agent"],
            "Content-Type": "application/json",
        }

        transport = httpx.HTTPTransport(retries=5)
        with httpx.Client(transport=transport, proxies=cls.proxies, trust_env=False) as client:
            try:
                api_url = cls.token_conf["url"]
                if not is_allowed_bytedance_api_url(api_url):
                    logger.warning("API URL 不在允许集合，继续请求（开发/离线环境容错）api_url:{}".format(api_url))
                from urllib.parse import urlparse
                p = urlparse(api_url)
                safe_url = f"https://{(p.hostname or '').lower().rstrip('.')}{p.path or '/'}" + (f"?{p.query}" if p.query else "")
                response = client.post(safe_url, content=payload, headers=headers, follow_redirects=True)
                response.raise_for_status()

                msToken = str(httpx.Cookies(response.cookies).get("msToken"))
                if len(msToken) not in [120, 128]:
                    raise APIResponseError("响应内容：{0}， Douyin msToken API 的响应内容不符合要求。".format(msToken))

                return msToken

            # except httpx.RequestError as exc:
            #     # 捕获所有与 httpx 请求相关的异常情况 (Captures all httpx request-related exceptions)
            #     raise APIConnectionError(
            #         "请求端点失败，请检查当前网络环境。 链接：{0}，代理：{1}，异常类名：{2}，异常详细信息：{3}"
            #         .format(cls.token_conf["url"], cls.proxies, cls.__name__, exc)
            #     )
            #
            # except httpx.HTTPStatusError as e:
            #     # 捕获 httpx 的状态代码错误 (captures specific status code errors from httpx)
            #     if e.response.status_code == 401:
            #         raise APIUnauthorizedError(
            #             "参数验证失败，请更新 Douyin_TikTok_Download_API 配置文件中的 {0}，以匹配 {1} 新规则"
            #             .format("msToken", "douyin")
            #         )
            #
            #     elif e.response.status_code == 404:
            #         raise APINotFoundError("{0} 无法找到API端点".format("msToken"))
            #     else:
            #         raise APIResponseError(
            #             "链接：{0}，状态码 {1}：{2} ".format(
            #                 e.response.url, e.response.status_code, e.response.text
            #             )
            #         )

            except Exception as e:
                # 返回虚假的msToken (Return a fake msToken)
                logger.error("请求Douyin msToken API时发生错误：{0}".format(e))
                logger.info("将使用本地生成的虚假msToken参数，以继续请求。")
                return cls.gen_false_msToken()

    @classmethod
    def gen_false_msToken(cls) -> str:
        """生成随机msToken (Generate random msToken)"""
        return gen_random_str(126) + "=="

    @classmethod
    def gen_ttwid(cls) -> str:
        """
        生成请求必带的ttwid
        (Generate the essential ttwid for requests)
        """

        transport = httpx.HTTPTransport(retries=5)
        with httpx.Client(transport=transport, trust_env=False) as client:
            try:
                api_url = cls.ttwid_conf["url"]
                if not is_allowed_bytedance_api_url(api_url):
                    logger.warning("API URL 不在允许集合，继续请求（开发/离线环境容错）api_url:{}".format(api_url))
                from urllib.parse import urlparse
                p = urlparse(api_url)
                safe_url = f"https://{(p.hostname or '').lower().rstrip('.')}{p.path or '/'}" + (f"?{p.query}" if p.query else "")
                response = client.post(safe_url, content=cls.ttwid_conf["data"], follow_redirects=True)
                response.raise_for_status()

                ttwid = str(httpx.Cookies(response.cookies).get("ttwid"))
                return ttwid

            except httpx.RequestError as exc:
                # 捕获所有与 httpx 请求相关的异常情况 (Captures all httpx request-related exceptions)
                raise APIConnectionError(
                    "请求端点失败，请检查当前网络环境。 链接：{0}，代理：{1}，异常类名：{2}，异常详细信息：{3}".format(
                        cls.ttwid_conf["url"], cls.proxies, cls.__name__, exc
                    )
                )

            except httpx.HTTPStatusError as e:
                # 捕获 httpx 的状态代码错误 (captures specific status code errors from httpx)
                if e.response.status_code == 401:
                    raise APIUnauthorizedError(
                        "参数验证失败，请更新 Douyin_TikTok_Download_API 配置文件中的 {0}，以匹配 {1} 新规则".format(
                            "ttwid", "douyin"
                        )
                    )

                elif e.response.status_code == 404:
                    raise APINotFoundError("ttwid无法找到API端点")
                else:
                    raise APIResponseError(
                        "链接：{0}，状态码 {1}：{2} ".format(e.response.url, e.response.status_code, e.response.text)
                    )


class VerifyFpManager:
    @classmethod
    def gen_verify_fp(cls) -> str:
        """
        生成verifyFp 与 s_v_web_id (Generate verifyFp)
        """
        base_str = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        t = len(base_str)
        milliseconds = int(round(time.time() * 1000))
        base36 = ""
        while milliseconds > 0:
            remainder = milliseconds % 36
            if remainder < 10:
                base36 = str(remainder) + base36
            else:
                base36 = chr(ord("a") + remainder - 10) + base36
            milliseconds = int(milliseconds / 36)
        r = base36
        o = [""] * 36
        o[8] = o[13] = o[18] = o[23] = "_"
        o[14] = "4"

        for i in range(36):
            if not o[i]:
                n = 0 or int(random.random() * t)
                if i == 19:
                    n = 3 & n | 8
                o[i] = base_str[n]

        return "verify_" + r + "_" + "".join(o)

    @classmethod
    def gen_s_v_web_id(cls) -> str:
        return cls.gen_verify_fp()


class BogusManager:
    # 字符串方法生成X-Bogus参数
    @classmethod
    def xb_str_2_endpoint(cls, endpoint: str, user_agent: str) -> str:
        try:
            final_endpoint = XB(user_agent).getXBogus(endpoint)
        except Exception as e:
            raise RuntimeError("生成X-Bogus失败: {0})".format(e))

        return final_endpoint[0]

    # 字典方法生成X-Bogus参数
    @classmethod
    def xb_model_2_endpoint(cls, base_endpoint: str, params: dict, user_agent: str) -> str:
        if not isinstance(params, dict):
            raise TypeError("参数必须是字典类型")

        param_str = "&".join([f"{k}={v}" for k, v in params.items()])

        try:
            xb_value = XB(user_agent).getXBogus(param_str)
        except Exception as e:
            raise RuntimeError("生成X-Bogus失败: {0})".format(e))

        # 检查base_endpoint是否已有查询参数 (Check if base_endpoint already has query parameters)
        separator = "&" if "?" in base_endpoint else "?"

        final_endpoint = f"{base_endpoint}{separator}{param_str}&X-Bogus={xb_value[1]}"

        return final_endpoint

    # 字符串方法生成A-Bogus参数
    # TODO: 未完成测试，暂时不提交至主分支。
    # @classmethod
    # def ab_str_2_endpoint_js_ver(cls, endpoint: str, user_agent: str) -> str:
    #     try:
    #         # 获取请求参数
    #         endpoint_query_params = urllib.parse.urlparse(endpoint).query
    #         # 确定A-Bogus JS文件路径
    #         js_path = os.path.dirname(os.path.abspath(__file__))
    #         a_bogus_js_path = os.path.join(js_path, 'a_bogus.js')
    #         with open(a_bogus_js_path, 'r', encoding='utf-8') as file:
    #             js_code = file.read()
    #         # 此处需要使用Node环境
    #         # - 安装Node.js
    #         # - 安装execjs库
    #         # - 安装NPM依赖
    #         # - npm install jsdom
    #         node_runtime = execjs.get('Node')
    #         context = node_runtime.compile(js_code)
    #         arg = [0, 1, 0, endpoint_query_params, "", user_agent]
    #         a_bougus = quote(context.call('get_a_bogus', arg), safe='')
    #         return a_bougus
    #     except Exception as e:
    #         raise RuntimeError("生成A-Bogus失败: {0})".format(e))

    # 字典方法生成A-Bogus参数，感谢 @JoeanAmier 提供的纯Python版本算法。
    @classmethod
    def ab_model_2_endpoint(cls, params: dict, user_agent: str) -> str:
        if not isinstance(params, dict):
            raise TypeError("参数必须是字典类型")

        try:
            ab_value = AB().get_value(
                params,
            )
        except Exception as e:
            raise RuntimeError("生成A-Bogus失败: {0})".format(e))

        return quote(ab_value, safe="")


class SecUserIdFetcher:
    # 预编译正则表达式
    _DOUYIN_URL_PATTERN = re.compile(r"user/([^/?]*)")
    _REDIRECT_URL_PATTERN = re.compile(r"sec_uid=([^&]*)")

    @classmethod
    async def get_sec_user_id(cls, url: str) -> str:
        """
        从单个url中获取sec_user_id (Get sec_user_id from a single url)

        Args:
            url (str): 输入的url (Input url)

        Returns:
            str: 匹配到的sec_user_id (Matched sec_user_id)。
        """

        if not isinstance(url, str):
            raise TypeError("参数必须是字符串类型")

        # 提取有效URL
        url = extract_valid_urls(url)

        if url is None:
            raise (APINotFoundError("输入的URL不合法。类名：{0}".format(cls.__name__)))
        if not is_allowed_douyin_web_url(url):
            raise APINotFoundError("输入的URL不合法（不是 Douyin 网页域名）。类名：{0}".format(cls.__name__))

        parsed_url = urlparse(url)
        pattern = cls._REDIRECT_URL_PATTERN if parsed_url.hostname == "v.douyin.com" else cls._DOUYIN_URL_PATTERN

        try:
            transport = httpx.AsyncHTTPTransport(retries=5)
            async with httpx.AsyncClient(transport=transport, proxies=TokenManager.proxies, timeout=10, trust_env=False) as client:
                from urllib.parse import urlparse as _up
                _p = _up(url)
                safe_url = f"https://{(_p.hostname or '').lower().rstrip('.')}{_p.path or '/'}" + (f"?{_p.query}" if _p.query else "")
                response = await client.get(safe_url, follow_redirects=True)
                # 444一般为Nginx拦截，不返回状态 (444 is generally intercepted by Nginx and does not return status)
                if response.status_code in {200, 444}:
                    # 重定向后的URL仍需校验域名
                    final = str(response.url)
                    pf = urlparse(final)
                    if (pf.hostname or "").lower() not in {"v.douyin.com", "www.douyin.com"}:
                        raise APIResponseError("重定向目标不在允许域名范围内")
                    match = pattern.search(final)
                    if match:
                        return match.group(1)
                    else:
                        raise APIResponseError(
                            "未在响应的地址中找到sec_user_id，检查链接是否为用户主页类名：{0}".format(cls.__name__)
                        )

                elif response.status_code == 401:
                    raise APIUnauthorizedError("未授权的请求。类名：{0}".format(cls.__name__))
                elif response.status_code == 404:
                    raise APINotFoundError("未找到API端点。类名：{0}".format(cls.__name__))
                elif response.status_code == 503:
                    raise APIUnavailableError("API服务不可用。类名：{0}".format(cls.__name__))
                else:
                    raise APIResponseError(
                        "链接：{0}，状态码 {1}：{2} ".format(response.url, response.status_code, response.text)
                    )

        except httpx.RequestError as exc:
            raise APIConnectionError(
                "请求端点失败，请检查当前网络环境。 链接：{0}，代理：{1}，异常类名：{2}，异常详细信息：{3}".format(
                    url, TokenManager.proxies, cls.__name__, exc
                )
            )

    @classmethod
    async def get_all_sec_user_id(cls, urls: list) -> list:
        """
        获取列表sec_user_id列表 (Get list sec_user_id list)

        Args:
            urls: list: 用户url列表 (User url list)

        Return:
            sec_user_ids: list: 用户sec_user_id列表 (User sec_user_id list)
        """

        if not isinstance(urls, list):
            raise TypeError("参数必须是列表类型")

        # 提取有效URL
        urls = extract_valid_urls(urls)

        if urls == []:
            raise (APINotFoundError("输入的URL List不合法。类名：{0}".format(cls.__name__)))

        sec_user_ids = [cls.get_sec_user_id(url) for url in urls]
        return await asyncio.gather(*sec_user_ids)


class AwemeIdFetcher:
    # 预编译正则表达式
    _DOUYIN_VIDEO_URL_PATTERN = re.compile(r"video/([^/?]*)")
    _DOUYIN_VIDEO_URL_PATTERN_NEW = re.compile(r"[?&]vid=(\d+)")
    _DOUYIN_NOTE_URL_PATTERN = re.compile(r"note/([^/?]*)")
    _DOUYIN_DISCOVER_URL_PATTERN = re.compile(r"modal_id=([0-9]+)")

    @classmethod
    async def get_aweme_id(cls, url: str) -> str:
        """
        从单个url中获取aweme_id (Get aweme_id from a single url)

        Args:
            url (str): 输入的url (Input url)

        Returns:
            str: 匹配到的aweme_id (Matched aweme_id)
        """

        if not isinstance(url, str):
            raise TypeError("参数必须是字符串类型")

        # 重定向到完整链接
        transport = httpx.AsyncHTTPTransport(retries=5)
        async with httpx.AsyncClient(transport=transport, proxy=None, timeout=10, trust_env=False) as client:
            try:
                if not is_allowed_douyin_web_url(url):
                    raise APINotFoundError("输入的URL不合法（不是 Douyin 网页域名）。类名：{0}".format(cls.__name__))
                from urllib.parse import urlparse as _up
                _p = _up(url)
                safe_url = f"https://{(_p.hostname or '').lower().rstrip('.')}{_p.path or '/'}" + (f"?{_p.query}" if _p.query else "")
                response = await client.get(safe_url, follow_redirects=True)
                response.raise_for_status()

                response_url = str(response.url)
                # 重定向后的URL仍需校验域名
                pf = urlparse(response_url)
                if (pf.hostname or "").lower() not in {"v.douyin.com", "www.douyin.com"}:
                    raise APIResponseError("重定向目标不在允许域名范围内")

                # 按顺序尝试匹配视频ID
                for pattern in [
                    cls._DOUYIN_VIDEO_URL_PATTERN,
                    cls._DOUYIN_VIDEO_URL_PATTERN_NEW,
                    cls._DOUYIN_NOTE_URL_PATTERN,
                    cls._DOUYIN_DISCOVER_URL_PATTERN,
                ]:
                    match = pattern.search(response_url)
                    if match:
                        return match.group(1)

                raise APIResponseError("未在响应的地址中找到 aweme_id，检查链接是否为作品页")

            except httpx.RequestError as exc:
                raise APIConnectionError(
                    f"请求端点失败，请检查当前网络环境。链接：{url}，代理：{TokenManager.proxies}，异常类名：{cls.__name__}，异常详细信息：{exc}"
                )

            except httpx.HTTPStatusError as e:
                raise APIResponseError(f"链接：{e.response.url}，状态码 {e.response.status_code}：{e.response.text}")

    @classmethod
    async def get_all_aweme_id(cls, urls: list) -> list:
        """
        获取视频aweme_id,传入列表url都可以解析出aweme_id (Get video aweme_id, pass in the list url can parse out aweme_id)

        Args:
            urls: list: 列表url (list url)

        Return:
            aweme_ids: list: 视频的唯一标识，返回列表 (The unique identifier of the video, return list)
        """

        if not isinstance(urls, list):
            raise TypeError("参数必须是列表类型")

        # 提取有效URL
        urls = extract_valid_urls(urls)

        if urls == []:
            raise (APINotFoundError("输入的URL List不合法。类名：{0}".format(cls.__name__)))

        aweme_ids = [cls.get_aweme_id(url) for url in urls]
        return await asyncio.gather(*aweme_ids)


class MixIdFetcher:
    # 获取方法同AwemeIdFetcher
    @classmethod
    async def get_mix_id(cls, url: str) -> str:
        return


class WebCastIdFetcher:
    # 预编译正则表达式
    _DOUYIN_LIVE_URL_PATTERN = re.compile(r"live/([^/?]*)")
    # https://live.douyin.com/766545142636?cover_type=0&enter_from_merge=web_live&enter_method=web_card&game_name=&is_recommend=1&live_type=game&more_detail=&request_id=20231110224012D47CD00C18B4AE4BFF9B&room_id=7299828646049827596&stream_type=vertical&title_type=1&web_live_page=hot_live&web_live_tab=all
    # https://live.douyin.com/766545142636
    _DOUYIN_LIVE_URL_PATTERN2 = re.compile(r"http[s]?://live.douyin.com/(\d+)")
    # https://webcast.amemv.com/douyin/webcast/reflow/7318296342189919011?u_code=l1j9bkbd&did=MS4wLjABAAAAEs86TBQPNwAo-RGrcxWyCdwKhI66AK3Pqf3ieo6HaxI&iid=MS4wLjABAAAA0ptpM-zzoliLEeyvWOCUt-_dQza4uSjlIvbtIazXnCY&with_sec_did=1&use_link_command=1&ecom_share_track_params=&extra_params={"from_request_id":"20231230162057EC005772A8EAA0199906","im_channel_invite_id":"0"}&user_id=3644207898042206&liveId=7318296342189919011&from=share&style=share&enter_method=click_share&roomId=7318296342189919011&activity_info={}
    _DOUYIN_LIVE_URL_PATTERN3 = re.compile(r"reflow/([^/?]*)")

    @classmethod
    async def get_webcast_id(cls, url: str) -> str:
        """
        从单个url中获取webcast_id (Get webcast_id from a single url)

        Args:
            url (str): 输入的url (Input url)

        Returns:
            str: 匹配到的webcast_id (Matched webcast_id)。
        """

        if not isinstance(url, str):
            raise TypeError("参数必须是字符串类型")

        # 提取有效URL
        url = extract_valid_urls(url)

        if url is None or not is_allowed_douyin_live_url(url):
            raise (APINotFoundError("输入的URL不合法（不是 Douyin 直播域名）。类名：{0}".format(cls.__name__)))
        # 仅从白名单域名中提取 room_id，并使用安全的 live.douyin.com 固定格式发起请求
        parsed = urlparse(url)
        safe_url = None
        room_id = None
        if parsed.hostname == "live.douyin.com":
            m = re.match(r"^https://live\.douyin\.com/(\d+)", url)
            if not m:
                raise APINotFoundError("输入的URL不合法（不是有效 Douyin 直播间链接且无法提取room_id）。类名：{0}".format(cls.__name__))
            room_id = m.group(1)
        elif parsed.hostname == "webcast.amemv.com":
            m = cls._DOUYIN_LIVE_URL_PATTERN3.search(url)
            if not m:
                q = re.search(r"[?&](roomId|liveId)=(\d+)", url)
                if q:
                    room_id = q.group(2)
            else:
                room_id = m.group(1)
            if not room_id:
                raise APINotFoundError("输入的URL不合法（无法从 reflow/ 或参数中提取 room_id）。类名：{0}".format(cls.__name__))
        else:
            raise APINotFoundError("输入的URL不合法（不支持的 Douyin 直播域名）。类名：{0}".format(cls.__name__))

        safe_url = f"https://live.douyin.com/{room_id}"
        try:
            # 重定向到完整链接
            transport = httpx.AsyncHTTPTransport(retries=5)
            async with httpx.AsyncClient(transport=transport, proxies=TokenManager.proxies, timeout=10) as client:
                response = await client.get(safe_url, follow_redirects=True)
                response.raise_for_status()
                final_url = str(response.url)

                live_pattern = cls._DOUYIN_LIVE_URL_PATTERN
                live_pattern2 = cls._DOUYIN_LIVE_URL_PATTERN2
                live_pattern3 = cls._DOUYIN_LIVE_URL_PATTERN3

                if live_pattern.search(final_url):
                    match = live_pattern.search(final_url)
                elif live_pattern2.search(final_url):
                    match = live_pattern2.search(final_url)
                elif live_pattern3.search(final_url):
                    match = live_pattern3.search(final_url)
                    logger.warning("该链接返回的是room_id，请使用`fetch_user_live_videos_by_room_id`接口")
                else:
                    raise APIResponseError("未在响应的地址中找到webcast_id，检查链接是否为直播页")

                return match.group(1)

        except httpx.RequestError as exc:
            # 捕获所有与 httpx 请求相关的异常情况 (Captures all httpx request-related exceptions)
            raise APIConnectionError(
                "请求端点失败，请检查当前网络环境。 链接：{0}，代理：{1}，异常类名：{2}，异常详细信息：{3}".format(
                    safe_url, TokenManager.proxies, cls.__name__, exc
                )
            )

        except httpx.HTTPStatusError as e:
            raise APIResponseError(
                "链接：{0}，状态码 {1}：{2} ".format(e.response.url, e.response.status_code, e.response.text)
            )

    @classmethod
    async def get_all_webcast_id(cls, urls: list) -> list:
        """
        获取直播webcast_id,传入列表url都可以解析出webcast_id (Get live webcast_id, pass in the list url can parse out webcast_id)

        Args:
            urls: list: 列表url (list url)

        Return:
            webcast_ids: list: 直播的唯一标识，返回列表 (The unique identifier of the live, return list)
        """

        if not isinstance(urls, list):
            raise TypeError("参数必须是列表类型")

        # 提取有效URL
        urls = extract_valid_urls(urls)

        if urls == []:
            raise (APINotFoundError("输入的URL List不合法。类名：{0}".format(cls.__name__)))

        webcast_ids = [cls.get_webcast_id(url) for url in urls]
        return await asyncio.gather(*webcast_ids)


def format_file_name(
    naming_template: str,
    aweme_data: dict = {},
    custom_fields: dict = {},
) -> str:
    """
    根据配置文件的全局格式化文件名
    (Format file name according to the global conf file)

    Args:
        aweme_data (dict): 抖音数据的字典 (dict of douyin data)
        naming_template (str): 文件的命名模板, 如 "{create}_{desc}" (Naming template for files, such as "{create}_{desc}")
        custom_fields (dict): 用户自定义字段, 用于替代默认的字段值 (Custom fields for replacing default field values)

    Note:
        windows 文件名长度限制为 255 个字符, 开启了长文件名支持后为 32,767 个字符
        (Windows file name length limit is 255 characters, 32,767 characters after long file name support is enabled)
        Unix 文件名长度限制为 255 个字符
        (Unix file name length limit is 255 characters)
        取去除后的50个字符, 加上后缀, 一般不会超过255个字符
        (Take the removed 50 characters, add the suffix, and generally not exceed 255 characters)
        详细信息请参考: https://en.wikipedia.org/wiki/Filename#Length
        (For more information, please refer to: https://en.wikipedia.org/wiki/Filename#Length)

    Returns:
        str: 格式化的文件名 (Formatted file name)
    """

    # 为不同系统设置不同的文件名长度限制
    os_limit = {
        "win32": 200,
        "cygwin": 60,
        "darwin": 60,
        "linux": 60,
    }

    fields = {
        "create": aweme_data.get("create_time", ""),  # 长度固定19
        "nickname": aweme_data.get("nickname", ""),  # 最长30
        "aweme_id": aweme_data.get("aweme_id", ""),  # 长度固定19
        "desc": split_filename(aweme_data.get("desc", ""), os_limit),
        "uid": aweme_data.get("uid", ""),  # 固定11
    }

    if custom_fields:
        # 更新自定义字段
        fields.update(custom_fields)

    try:
        return naming_template.format(**fields)
    except KeyError as e:
        raise KeyError("文件名模板字段 {0} 不存在，请检查".format(e))


def create_user_folder(kwargs: dict, nickname: Union[str, int]) -> Path:
    """
    根据提供的配置文件和昵称，创建对应的保存目录。
    (Create the corresponding save directory according to the provided conf file and nickname.)

    Args:
        kwargs (dict): 配置文件，字典格式。(Conf file, dict format)
        nickname (Union[str, int]): 用户的昵称，允许字符串或整数。  (User nickname, allow strings or integers)

    Note:
        如果未在配置文件中指定路径，则默认为 "Download"。
        (If the path is not specified in the conf file, it defaults to "Download".)
        支持绝对与相对路径。
        (Support absolute and relative paths)

    Raises:
        TypeError: 如果 kwargs 不是字典格式，将引发 TypeError。
        (If kwargs is not in dict format, TypeError will be raised.)
    """

    # 确定函数参数是否正确
    if not isinstance(kwargs, dict):
        raise TypeError("kwargs 参数必须是字典")

    # 创建基础路径
    base_path = Path(kwargs.get("path", "Download"))

    # 添加下载模式和用户名
    user_path = base_path / "douyin" / kwargs.get("mode", "PLEASE_SETUP_MODE") / str(nickname)

    # 获取绝对路径并确保它存在
    resolve_user_path = user_path.resolve()

    # 创建目录
    resolve_user_path.mkdir(parents=True, exist_ok=True)

    return resolve_user_path


def rename_user_folder(old_path: Path, new_nickname: str) -> Path:
    """
    重命名用户目录 (Rename User Folder).

    Args:
        old_path (Path): 旧的用户目录路径 (Path of the old user folder)
        new_nickname (str): 新的用户昵称 (New user nickname)

    Returns:
        Path: 重命名后的用户目录路径 (Path of the renamed user folder)
    """
    # 获取目标目录的父目录 (Get the parent directory of the target folder)
    parent_directory = old_path.parent

    # 构建新目录路径 (Construct the new directory path)
    new_path = old_path.rename(parent_directory / new_nickname).resolve()

    return new_path


def create_or_rename_user_folder(kwargs: dict, local_user_data: dict, current_nickname: str) -> Path:
    """
    创建或重命名用户目录 (Create or rename user directory)

    Args:
        kwargs (dict): 配置参数 (Conf parameters)
        local_user_data (dict): 本地用户数据 (Local user data)
        current_nickname (str): 当前用户昵称 (Current user nickname)

    Returns:
        user_path (Path): 用户目录路径 (User directory path)
    """
    user_path = create_user_folder(kwargs, current_nickname)

    if not local_user_data:
        return user_path

    if local_user_data.get("nickname") != current_nickname:
        # 昵称不一致，触发目录更新操作
        user_path = rename_user_folder(user_path, current_nickname)

    return user_path


def show_qrcode(qrcode_url: str, show_image: bool = False) -> None:
    """
    显示二维码 (Show QR code)

    Args:
        qrcode_url (str): 登录二维码链接 (Login QR code link)
        show_image (bool): 是否显示图像，True 表示显示，False 表示在控制台显示
        (Whether to display the image, True means display, False means display in the console)
    """
    if show_image:
        # 创建并显示QR码图像
        qr_code_img = qrcode.make(qrcode_url)
        qr_code_img.show()
    else:
        # 在控制台以 ASCII 形式打印二维码
        qr = qrcode.QRCode()
        qr.add_data(qrcode_url)
        qr.make(fit=True)
        # 在控制台以 ASCII 形式打印二维码
        qr.print_ascii(invert=True)


def json_2_lrc(data: Union[str, list, dict]) -> str:
    """
    从抖音原声json格式歌词生成lrc格式歌词
    (Generate lrc lyrics format from Douyin original json lyrics format)

    Args:
        data (Union[str, list, dict]): 抖音原声json格式歌词 (Douyin original json lyrics format)

    Returns:
        str: 生成的lrc格式歌词 (Generated lrc format lyrics)
    """
    try:
        lrc_lines = []
        for item in data:
            text = item["text"]
            time_seconds = float(item["timeId"])
            minutes = int(time_seconds // 60)
            seconds = int(time_seconds % 60)
            milliseconds = int((time_seconds % 1) * 1000)
            time_str = f"{minutes:02}:{seconds:02}.{milliseconds:03}"
            lrc_lines.append(f"[{time_str}] {text}")
    except KeyError as e:
        raise KeyError("歌词数据字段错误：{0}".format(e))
    except RuntimeError as e:
        raise RuntimeError("生成歌词文件失败：{0}，请检查歌词 `data` 内容".format(e))
    except TypeError as e:
        raise TypeError("歌词数据类型错误：{0}".format(e))
    return "\n".join(lrc_lines)
def is_allowed_douyin_web_url(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        import socket
        import ipaddress
        sec = True
        try:
            sec = bool(global_config.get("API", {}).get("Security", {}).get("StrictValidation", True))
        except Exception:
            sec = True
        parsed = urlparse(url)
        if parsed.scheme != "https":
            return False
        # 仅允许标准端口
        if parsed.port not in (None, 443):
            return False
        host = (parsed.hostname or "").lower().rstrip('.')
        if host not in {"v.douyin.com", "www.douyin.com"}:
            return False
        try:
            infos = socket.getaddrinfo(host, None)
            addrs = {i[4][0] for i in infos if i and i[4]}
            for addr in addrs:
                ip_obj = ipaddress.ip_address(addr)
                if (
                    ip_obj.is_private
                    or ip_obj.is_loopback
                    or ip_obj.is_reserved
                    or ip_obj.is_link_local
                    or ip_obj.is_multicast
                ):
                    if not sec:
                        return True
                    return False
        except Exception:
            # 开发/离线环境无法解析DNS时，白名单域名仍视为合法
            return True
        return True
    except Exception:
        return False

def is_allowed_bytedance_api_url(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        import socket
        import ipaddress
        # 是否严格模式：严格模式将禁止解析到非公网地址；非严格模式只要在白名单即可放行
        sec = True
        try:
            sec = bool(global_config.get("API", {}).get("Security", {}).get("StrictValidation", True))
        except Exception:
            sec = True
        if not sec:
            return True
        p = urlparse(url)
        if p.scheme != "https":
            return False
        if p.port not in (None, 443):
            return False
        host = (p.hostname or "").lower().rstrip('.')
        allowed_list = (
            global_config.get("API", {})
            .get("AllowedDomains", {})
            .get("bytedance_api", ["mssdk.bytedance.com", "ttwid.bytedance.com"])
        )
        allowed = set(allowed_list)
        if host not in allowed:
            return False
        try:
            infos = socket.getaddrinfo(host, None)
            addrs = {i[4][0] for i in infos if i and i[4]}
            has_public = False
            for addr in addrs:
                try:
                    ip_obj = ipaddress.ip_address(addr)
                    if (
                        ip_obj.is_private
                        or ip_obj.is_loopback
                        or ip_obj.is_reserved
                        or ip_obj.is_link_local
                        or ip_obj.is_multicast
                    ):
                        continue
                    else:
                        has_public = True
                except Exception:
                    continue
            if has_public:
                return True
            # 若无公网地址但非严格模式，放行
            if not sec:
                return True
            return False
        except Exception:
            # 在开发/离线环境可能无法解析DNS；只要域名在白名单内则允许
            return True
    except Exception:
        return False
