import asyncio
import os
import re
import tempfile
import time
import zipfile
from pathlib import Path

import aiofiles
import httpx
import yaml
from fastapi import APIRouter, HTTPException, Query, Request  # 导入FastAPI组件
from starlette.responses import FileResponse
from werkzeug.utils import secure_filename

from app.api.models.APIResponseModel import ErrorResponseModel  # 导入响应模型
from crawlers.hybrid.hybrid_crawler import HybridCrawler  # 导入混合数据爬虫
from crawlers.utils.logger import logger
from crawlers.utils.utils import extract_valid_urls

router = APIRouter()
HybridCrawler = HybridCrawler()

# FFmpeg 合并并发控制（作为简单队列，限制同时仅运行一个合并任务）
_ffmpeg_sem = asyncio.Semaphore(1)

# 读取上级再上级目录的配置文件
config_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "config",
    "config.yaml",
)
with open(config_path, "r", encoding="utf-8") as file:
    config = yaml.safe_load(file)


def _norm_path(p: str) -> str:
    return os.path.realpath(os.path.normpath(p))


def _is_under(root: str, p: str) -> bool:
    try:
        root_n = _norm_path(root)
        p_n = _norm_path(p)
        common = os.path.commonpath([p_n, root_n])
        return common == root_n and p_n != root_n
    except Exception:
        return False


def _is_under_any(p: str, roots: list[str]) -> bool:
    try:
        p_n = _norm_path(p)
        for r in roots:
            r_n = _norm_path(r)
            common = os.path.commonpath([p_n, r_n])
            if common == r_n and p_n != r_n:
                return True
        return False
    except Exception:
        return False


def _safe_unlink(p: str, roots: list[str]):
    try:
        if _is_under_any(p, roots) and Path(p).is_file():
            os.unlink(p)
    except Exception:
        pass


def _valid_filename(name: str) -> bool:
    if not name:
        return False
    if "/" in name or "\\" in name:
        return False
    if name in {".", ".."}:
        return False
    if name.startswith("."):
        return False
    if name.startswith(os.sep):
        return False
    if ".." in name:
        return False
    return True


def _is_allowed_download_url(platform: str, url: str) -> bool:
    try:
        from urllib.parse import urlparse
        import socket
        import ipaddress
        p = urlparse(url)
        if p.scheme != "https":
            return False
        # 仅允许标准端口
        if p.port not in (None, 443):
            return False
        # 禁止在URL中携带用户信息
        if p.username or p.password:
            return False
        # 规范化主机名并转为IDNA ASCII
        host = (p.hostname or "").lower().rstrip('.')
        try:
            host_ascii = host.encode('idna').decode('ascii')
        except Exception:
            return False
        allow = (
            config.get("API", {})
            .get("AllowedDomains", {})
            .get("download", {})
            .get(platform, [])
        ).get(platform, [])
        if not any(host_ascii == a.lstrip('.') or host_ascii.endswith(a) for a in allow):
            return False
        # 解析DNS并拒绝私网/本地/保留等地址
        try:
            infos = socket.getaddrinfo(host_ascii, None)
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
                    return False
        except Exception:
            return False
        return True
    except Exception:
        return False


async def _safe_get(url: str, platform: str, headers: dict | None = None) -> httpx.Response:
    sec = bool(config.get("API", {}).get("Security", {}).get("StrictValidation", True))
    if not sec:
        async with httpx.AsyncClient(trust_env=True, follow_redirects=True, timeout=httpx.Timeout(30)) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response
    # 就地校验并重建安全URL，增强静态分析可见性
    from urllib.parse import urlparse
    import socket
    import ipaddress
    p = urlparse(url)
    if p.scheme != "https":
        raise HTTPException(status_code=400, detail=_strict_msg(platform, "仅允许HTTPS", p.hostname or ""))
    if p.port not in (None, 443):
        raise HTTPException(status_code=400, detail=_strict_msg(platform, "仅允许标准端口443", p.hostname or ""))
    if p.username or p.password:
        raise HTTPException(status_code=400, detail=_strict_msg(platform, "URL包含用户名/密码信息", p.hostname or ""))
    host = (p.hostname or "").lower().rstrip('.')
    try:
        host_ascii = host.encode('idna').decode('ascii')
    except Exception:
        raise HTTPException(status_code=400, detail=_strict_msg(platform, "域名IDNA解析失败", host))
    allow = (
        config.get("API", {})
        .get("AllowedDomains", {})
        .get("download", {})
        .get(platform, [])
    ).get(platform, [])
    if not any(host_ascii == a.lstrip('.') or host_ascii.endswith(a) for a in allow):
        raise HTTPException(status_code=400, detail=_strict_msg(platform, "域名不在白名单", host))
    try:
        infos = socket.getaddrinfo(host_ascii, None)
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
                raise HTTPException(status_code=400, detail=_strict_msg(platform, "DNS解析到私网/保留地址", host, list(addrs)))
    except Exception:
        raise HTTPException(status_code=400, detail=_strict_msg(platform, "DNS解析失败", host))
    safe_url = f"https://{host_ascii}{p.path or '/'}" + (f"?{p.query}" if p.query else "")
    async with httpx.AsyncClient(trust_env=False, follow_redirects=True, timeout=httpx.Timeout(30)) as client:
        response = await client.get(safe_url, headers=headers)
        chain = list(response.history) + [response]
        for r in chain:
            if not _is_allowed_download_url(platform, str(r.url)):
                from urllib.parse import urlparse as _up
                _ru = _up(str(r.url))
                raise HTTPException(status_code=400, detail=_strict_msg(platform, "重定向目标不在白名单", host=_ru.hostname or ""))
        response.raise_for_status()
        return response


async def fetch_data(url: str, platform: str, headers: dict = None):
    headers = (
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        if headers is None
        else headers.get("headers")
    )
    return await _safe_get(url, platform, headers=headers)


# 下载视频专用
async def fetch_data_stream(url: str, platform: str, request: Request, headers: dict = None, file_path: str = None):
    headers = (
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        if headers is None
        else headers.get("headers")
    )
    sec = bool(config.get("API", {}).get("Security", {}).get("StrictValidation", True))
    if sec and not _is_allowed_download_url(platform, url):
        from urllib.parse import urlparse as _up
        _pu = _up(url)
        raise HTTPException(status_code=400, detail=_strict_msg(platform, "初始URL不在白名单", host=_pu.hostname or ""))
    async with httpx.AsyncClient(
        trust_env=not sec,
        timeout=httpx.Timeout(60),
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        follow_redirects=True,
    ) as client:
        # 预检以解析最终URL并校验重定向链路（仅严格模式）
        from urllib.parse import urlparse
        import socket
        import ipaddress
        p = urlparse(url)
        if sec and (p.scheme != "https" or p.port not in (None, 443) or p.username or p.password):
            raise HTTPException(status_code=400, detail=_strict_msg(platform, "仅允许HTTPS且标准端口，无用户信息", host=p.hostname or ""))
        host = (p.hostname or "").lower().rstrip('.')
        try:
            host_ascii = host.encode('idna').decode('ascii')
        except Exception:
            return False
        allow = (
            config.get("API", {})
            .get("AllowedDomains", {})
            .get("download", {})
            .get(platform, [])
        ).get(platform, [])
        if sec and not any(host_ascii == a.lstrip('.') or host_ascii.endswith(a) for a in allow):
            raise HTTPException(status_code=400, detail=_strict_msg(platform, "域名不在白名单", host_ascii))
        try:
            infos = socket.getaddrinfo(host_ascii, None)
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
                    if sec:
                        raise HTTPException(status_code=400, detail=_strict_msg(platform, "DNS解析到私网/保留地址", host_ascii, list(addrs)))
        except Exception:
            if sec:
                raise HTTPException(status_code=400, detail=_strict_msg(platform, "DNS解析失败", host_ascii))
        safe_url = f"https://{host_ascii}{p.path or '/'}" + (f"?{p.query}" if p.query else "")
        preflight = await client.get(safe_url if sec else url, headers=headers)
        chain = list(preflight.history) + [preflight]
        if sec:
            for r in chain:
                if not _is_allowed_download_url(platform, str(r.url)):
                    from urllib.parse import urlparse as _up
                    _ru = _up(str(r.url))
                    raise HTTPException(status_code=400, detail=_strict_msg(platform, "重定向目标不在白名单", host=_ru.hostname or ""))
        final_url = str(preflight.url)
        async with client.stream("GET", final_url if sec else url, headers=headers, follow_redirects=not sec) as response:
            response.raise_for_status()

            # 流式保存文件
            root_path = _norm_path(config.get("API").get("Download_Path"))
            temp_root = _norm_path(tempfile.gettempdir())
            allowed_roots = [root_path, temp_root]
            file_path = _norm_path(file_path)
            if not _is_under_any(file_path, allowed_roots):
                return False
            import os as _os
            full = _norm_path(file_path)
            bases = [
                _norm_path(root_path),
                _norm_path(temp_root),
            ]
            if not any(_os.path.commonpath([full, b]) == b and full != b for b in bases):
                return False
            async with aiofiles.open(file_path, "wb") as out_file:
                try:
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        if await request.is_disconnected():
                            await out_file.close()
                            _safe_unlink(file_path, allowed_roots)
                            return False
                        await out_file.write(chunk)
                except Exception:
                    try:
                        await out_file.close()
                    except Exception:
                        pass
                    _safe_unlink(file_path, allowed_roots)
                    return False
            return True


async def merge_bilibili_video_audio(
    video_url: str, audio_url: str, request: Request, output_path: str, headers: dict
) -> bool:
    """
    下载并合并 Bilibili 的视频流和音频流
    """
    try:
        # 创建临时文件
        with tempfile.NamedTemporaryFile(suffix=".m4v", delete=False) as video_temp:
            video_temp_path = video_temp.name
        with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as audio_temp:
            audio_temp_path = audio_temp.name

        # 下载视频流
        video_success = await fetch_data_stream(video_url, "bilibili", request, headers={"headers": headers}, file_path=video_temp_path)
        # 下载音频流
        audio_success = await fetch_data_stream(audio_url, "bilibili", request, headers={"headers": headers}, file_path=audio_temp_path)

        if not video_success or not audio_success:
            print("Failed to download video or audio stream")
            return False

        # 使用 FFmpeg 合并视频和音频（异步子进程，避免阻塞）
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            video_temp_path,
            "-i",
            audio_temp_path,
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-f",
            "mp4",
            output_path,
        ]
        logger.info("FFmpeg merge start output=%s", output_path)
        async with _ffmpeg_sem:
            process = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
            )
            stderr = b""
            if process.stderr is not None:
                stderr = await process.stderr.read()
            returncode = await process.wait()
        logger.info("FFmpeg finished code=%s", returncode)
        if stderr:
            logger.warning("FFmpeg stderr size=%d", len(stderr))

        # 清理临时文件
        try:
            os.unlink(video_temp_path)
            os.unlink(audio_temp_path)
        except Exception:
            pass

        return returncode == 0

    except Exception as e:
        # 清理临时文件
        try:
            os.unlink(video_temp_path)
            os.unlink(audio_temp_path)
        except Exception:
            pass
        logger.error("FFmpeg merge error: %s", e)
        return False


@router.get(
    "/download", summary="在线下载抖音|TikTok|Bilibili视频/图片/Online download Douyin|TikTok|Bilibili video/image"
)
async def download_file_hybrid(
    request: Request,
    url: str = Query(
        example="https://www.douyin.com/video/7372484719365098803",
        description="视频或图片的URL地址，支持抖音|TikTok|Bilibili的分享链接，例如：https://v.douyin.com/e4J8Q7A/ 或 https://www.bilibili.com/video/BV1xxxxxxxxx",
    ),
    prefix: bool = True,
    with_watermark: bool = False,
):
    """
    # [中文]
    ### 用途:
    - 在线下载抖音|TikTok|Bilibili 无水印或有水印的视频/图片
    - 通过传入的视频URL参数，获取对应的视频或图片数据，然后下载到本地。
    - 如果你在尝试直接访问TikTok单一视频接口的JSON数据中的视频播放地址时遇到HTTP403错误，那么你可以使用此接口来下载视频。
    - Bilibili视频会自动合并视频流和音频流，确保下载的视频有声音。
    - 这个接口会占用一定的服务器资源，所以在Demo站点是默认关闭的，你可以在本地部署后调用此接口。
    ### 参数:
    - url: 视频或图片的URL地址，支持抖音|TikTok|Bilibili的分享链接，例如：https://v.douyin.com/e4J8Q7A/ 或 https://www.bilibili.com/video/BV1xxxxxxxxx
    - prefix: 下载文件的前缀，默认为True，可以在配置文件中修改。
    - with_watermark: 是否下载带水印的视频或图片，默认为False。(注意：Bilibili没有水印概念)
    ### 返回:
    - 返回下载的视频或图片文件响应。

    # [English]
    ### Purpose:
    - Download Douyin|TikTok|Bilibili video/image with or without watermark online.
    - By passing the video URL parameter, get the corresponding video or image data, and then download it to the local.
    - If you encounter an HTTP403 error when trying to access the video playback address in the JSON data of the TikTok single video interface directly, you can use this interface to download the video.
    - Bilibili videos will automatically merge video and audio streams to ensure downloaded videos have sound.
    - This interface will occupy a certain amount of server resources, so it is disabled by default on the Demo site, you can call this interface after deploying it locally.
    ### Parameters:
    - url: The URL address of the video or image, supports Douyin|TikTok|Bilibili sharing links, for example: https://v.douyin.com/e4J8Q7A/ or https://www.bilibili.com/video/BV1xxxxxxxxx
    - prefix: The prefix of the downloaded file, the default is True, and can be modified in the configuration file.
    - with_watermark: Whether to download videos or images with watermarks, the default is False. (Note: Bilibili has no watermark concept)
    ### Returns:
    - Return the response of the downloaded video or image file.

    # [示例/Example]
    url: https://www.bilibili.com/video/BV1U5efz2Egn
    """
    # 是否开启此端点/Whether to enable this endpoint
    if not config["API"]["Download_Switch"]:
        code = 400
        message = "Download endpoint is disabled in the configuration file. | 配置文件中已禁用下载端点。"
        return ErrorResponseModel(
            code=code, message=message, router=request.url.path, params=dict(request.query_params)
        )

    # 开始解析数据/Start parsing data
    try:
        sanitized = extract_valid_urls(url)
        if not sanitized:
            code = 400
            return ErrorResponseModel(code=code, message="Invalid URL", router=request.url.path, params=dict(request.query_params))
        data = await HybridCrawler.hybrid_parsing_single_video(sanitized, minimal=True)
    except Exception as e:
        code = 400
        return ErrorResponseModel(code=code, message=str(e), router=request.url.path, params=dict(request.query_params))

    # 开始下载文件/Start downloading files
    try:
        data_type = data.get("type")
        platform = data.get("platform")
        if data_type not in {"video", "image"}:
            raise HTTPException(status_code=400, detail="Invalid data type")
        allowed_platforms = {"douyin", "tiktok", "bilibili"}
        if platform not in allowed_platforms:
            raise HTTPException(status_code=400, detail="Invalid platform specified")
        # allowed_types not used
        allowed_subdirs = {
            ("douyin", "video"): "douyin_video",
            ("douyin", "image"): "douyin_image",
            ("tiktok", "video"): "tiktok_video",
            ("tiktok", "image"): "tiktok_image",
            ("bilibili", "video"): "bilibili_video",
            ("bilibili", "image"): "bilibili_image",
        }
        video_id = data.get("video_id")
        safe_id = re.sub(r"[^A-Za-z0-9_\-]", "_", str(video_id))
        file_prefix = (
            re.sub(r"[^A-Za-z0-9_\-]", "_", str(config.get("API").get("Download_File_Prefix"))) if prefix else ""
        )
        root_path = _norm_path(config.get("API").get("Download_Path"))
        try:
            download_subdir = allowed_subdirs[(platform, data_type)]
        except KeyError:
            raise HTTPException(status_code=400, detail="Invalid directory combination")
        download_path = _norm_path(os.path.join(root_path, download_subdir))
        if not _is_under(root_path, download_path):
            raise HTTPException(status_code=400, detail="Invalid download path")
        base = _norm_path(root_path)
        full = _norm_path(download_path)
        import os as _os
        if _os.path.commonpath([full, base]) != base or full == base:
            raise HTTPException(status_code=400, detail="Invalid download path")

        # 确保目录存在/Ensure the directory exists
        os.makedirs(download_path, exist_ok=True)

        # 下载视频文件/Download video file
        if data_type == "video":
            raw_name = (
                f"{file_prefix}{platform}_{safe_id}.mp4"
                if not with_watermark
                else f"{file_prefix}{platform}_{safe_id}_watermark.mp4"
            )
            file_name = secure_filename(raw_name)
            if not _valid_filename(file_name):
                raise HTTPException(status_code=400, detail="Invalid filename")
            file_path = _norm_path(os.path.join(download_path, file_name))
            if not _is_under(root_path, file_path) or file_path == root_path:
                raise HTTPException(status_code=400, detail="Invalid file path")

            base = _norm_path(root_path)
            full = _norm_path(file_path)
            import os as _os
            if _os.path.commonpath([full, base]) == base and full != base and os.path.exists(file_path):
                return FileResponse(path=file_path, media_type="video/mp4", filename=file_name)

            # 获取对应平台的headers
            if platform == "tiktok":
                __headers = await HybridCrawler.TikTokWebCrawler.get_tiktok_headers()
            elif platform == "bilibili":
                __headers = await HybridCrawler.BilibiliWebCrawler.get_bilibili_headers()
            else:  # douyin
                __headers = await HybridCrawler.DouyinWebCrawler.get_douyin_headers()

            # Bilibili 特殊处理：音视频分离
            if platform == "bilibili":
                video_data = data.get("video_data", {})
                video_url = (
                    video_data.get("nwm_video_url_HQ") if not with_watermark else video_data.get("wm_video_url_HQ")
                )
                audio_url = video_data.get("audio_url")
                if not video_url or not audio_url:
                    raise HTTPException(status_code=500, detail="Failed to get video or audio URL from Bilibili")

                start = time.perf_counter()
                success = await merge_bilibili_video_audio(
                    video_url, audio_url, request, file_path, __headers.get("headers")
                )
                if not success:
                    raise HTTPException(status_code=500, detail="Failed to merge Bilibili video and audio streams")
                try:
                    size = os.path.getsize(file_path)
                except Exception:
                    size = 0
                from crawlers.utils.logger import log_metric

                log_metric(
                    "bilibili_merge",
                    output=file_path,
                    elapsed_ms=int((time.perf_counter() - start) * 1000),
                    size_bytes=size,
                )
            else:
                # 其他平台的常规处理
                url = (
                    data.get("video_data").get("nwm_video_url_HQ")
                    if not with_watermark
                    else data.get("video_data").get("wm_video_url_HQ")
                )
                start = time.perf_counter()
                success = await fetch_data_stream(url, platform, request, headers=__headers, file_path=file_path)
                if not success:
                    raise HTTPException(status_code=500, detail="An error occurred while fetching data")
                try:
                    size = os.path.getsize(file_path)
                except Exception:
                    size = 0
                from crawlers.utils.logger import log_metric

                log_metric(
                    f"{platform}_download",
                    output=file_path,
                    elapsed_ms=int((time.perf_counter() - start) * 1000),
                    size_bytes=size,
                )

            # # 保存文件
            # async with aiofiles.open(file_path, 'wb') as out_file:
            #     await out_file.write(response.content)

            # 返回文件内容
            return FileResponse(path=file_path, filename=file_name, media_type="video/mp4")

        # 下载图片文件/Download image file
        elif data_type == "image":
            # 压缩文件属性/Compress file properties
            raw_zip = (
                f"{file_prefix}{platform}_{safe_id}_images.zip"
                if not with_watermark
                else f"{file_prefix}{platform}_{safe_id}_images_watermark.zip"
            )
            zip_file_name = secure_filename(raw_zip)
            if not _valid_filename(zip_file_name):
                raise HTTPException(status_code=400, detail="Invalid filename")
            if not zip_file_name.lower().endswith(".zip"):
                raise HTTPException(status_code=400, detail="Invalid filename extension")
            zip_file_path = _norm_path(os.path.join(download_path, zip_file_name))
            if not _is_under(root_path, zip_file_path) or zip_file_path == root_path:
                raise HTTPException(status_code=400, detail="Invalid file path")

            # 判断文件是否存在，存在就直接返回、
            base = _norm_path(root_path)
            full = _norm_path(zip_file_path)
            if os.path.commonpath([full, base]) == base and full != base and os.path.exists(zip_file_path):
                return FileResponse(path=zip_file_path, filename=zip_file_name, media_type="application/zip")

            # 获取图片文件/Get image file
            urls = (
                data.get("image_data").get("no_watermark_image_list")
                if not with_watermark
                else data.get("image_data").get("watermark_image_list")
            )
            image_file_list = []
            for url in urls:
                # 请求图片文件/Request image file
                response = await fetch_data(url, platform)
                index = int(urls.index(url))
                content_type = (response.headers.get("content-type") or "").lower()
                subtype = ""
                if "/" in content_type:
                    _, subtype = content_type.split("/", 1)
                subtype = subtype.split(";")[0].strip()
                allowed_ext = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}
                if subtype not in allowed_ext:
                    raise HTTPException(status_code=400, detail="Unsupported content type for image download")
                file_format = subtype
                raw_img = (
                    f"{file_prefix}{platform}_{safe_id}_{index + 1}.{file_format}"
                    if not with_watermark
                    else f"{file_prefix}{platform}_{safe_id}_{index + 1}_watermark.{file_format}"
                )
                file_name = secure_filename(raw_img)
                if not _valid_filename(file_name):
                    raise HTTPException(status_code=400, detail="Invalid filename")
                file_path = _norm_path(os.path.join(download_path, file_name))
                # 额外的标准化路径前缀校验以满足静态扫描
                base = _norm_path(root_path)
                full = _norm_path(file_path)
                import os as _os
                if _os.path.commonpath([full, base]) != base or full == base:
                    raise HTTPException(status_code=400, detail="Invalid file path")
                image_file_list.append(file_path)

                # 保存文件/Save file
                async with aiofiles.open(file_path, "wb") as out_file:
                    await out_file.write(response.content)

            # 压缩文件/Compress file
            with zipfile.ZipFile(zip_file_path, "w") as zip_file:
                for image_file in image_file_list:
                    zip_file.write(image_file, os.path.basename(image_file))

            # 返回压缩文件/Return compressed file
            return FileResponse(path=zip_file_path, filename=zip_file_name, media_type="application/zip")

    # 异常处理/Exception handling
    except Exception as e:
        print(e)
        code = 400
        return ErrorResponseModel(code=code, message=str(e), router=request.url.path, params=dict(request.query_params))
def _strict_msg(platform: str, issue: str, host: str = "", ips: list[str] | None = None) -> str:
    allowed = (
        config.get("API", {})
        .get("AllowedDomains", {})
        .get("download", {})
        .get(platform, [])
    )
    extra = f" 域名：{host}" if host else ""
    ipinfo = f" 解析到IP：{ips}" if ips else ""
    logger.warning(
        "严格校验拒绝: %s.%s%s. 建议在 config/config.yaml → API.AllowedDomains.download.%s 添加需要的域后缀或确保公网解析。当前白名单: %s",
        issue,
        extra,
        ipinfo,
        platform,
        allowed,
    )
    return f"严格校验拒绝: {issue}.{extra}{ipinfo}"
