# FastAPI APP
import uvicorn
from fastapi import FastAPI, Depends, HTTPException, status, Security, Request
from fastapi.staticfiles import StaticFiles
from fastapi.security import APIKeyHeader
from app.api.router import router as api_router
from starlette.middleware.cors import CORSMiddleware

# PyWebIO APP
from app.web.app import MainView
from pywebio.platform.fastapi import asgi_app

# OS
import os

# YAML
import yaml
import asyncio

# Load Config

# 读取上级再上级目录的配置文件
config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.yaml')
with open(config_path, 'r', encoding='utf-8') as file:
    config = yaml.safe_load(file)


Host_IP = config['API']['Host_IP']
Host_Port = config['API']['Host_Port']

# API Tags
tags_metadata = [
    {
        "name": "Hybrid-API",
        "description": "**(混合数据接口/Hybrid-API data endpoints)**",
    },
    {
        "name": "Douyin-Web-API",
        "description": "**(抖音Web数据接口/Douyin-Web-API data endpoints)**",
    },
    {
        "name": "TikTok-Web-API",
        "description": "**(TikTok-Web-API数据接口/TikTok-Web-API data endpoints)**",
    },
    {
        "name": "TikTok-App-API",
        "description": "**(TikTok-App-API数据接口/TikTok-App-API data endpoints)**",
    },
    {
        "name": "Bilibili-Web-API",
        "description": "**(Bilibili-Web-API数据接口/Bilibili-Web-API data endpoints)**",
    },
    {
        "name": "iOS-Shortcut",
        "description": "**(iOS快捷指令数据接口/iOS-Shortcut data endpoints)**",
    },
    {
        "name": "Download",
        "description": "**(下载数据接口/Download data endpoints)**",
    },
]

version = config['API']['Version']
update_time = config['API']['Update_Time']
environment = config['API']['Environment']

description = f"""
### [中文]

#### 关于
- **项目名称**: 短流聚合 API（ShortStream Aggregator API）
- **版本**: `{version}`
- **更新时间**: `{update_time}`
- **环境**: `{environment}`
- **基于**: [Evil0ctal/Douyin_TikTok_Download_API@42784ffc83a72a516bfe952153ad7e2a3998d16c](https://github.com/Evil0ctal/Douyin_TikTok_Download_API/tree/42784ffc83a72a516bfe952153ad7e2a3998d16c) 开发
#### 备注
- 本项目仅供学习交流使用，不得用于违法用途，否则后果自负。

### [English]

#### About
- **Project Name**: ShortStream Aggregator API（短流聚合 API）
- **Version**: `{version}`
- **Last Updated**: `{update_time}`
- **Environment**: `{environment}`
- **Based on**: Developed from [Evil0ctal/Douyin_TikTok_Download_API@42784ffc83a72a516bfe952153ad7e2a3998d16c](https://github.com/Evil0ctal/Douyin_TikTok_Download_API/tree/42784ffc83a72a516bfe952153ad7e2a3998d16c)
#### Note
- This project is for learning and communication only, and shall not be used for illegal purposes, otherwise the consequences shall be borne by yourself.
"""

docs_url = config['API']['Docs_URL']
redoc_url = config['API']['Redoc_URL']

app = FastAPI(
    title="短流聚合 API（ShortStream Aggregator API）",
    description=description,
    version=version,
    openapi_tags=tags_metadata,
    docs_url=docs_url,  # 文档路径
    redoc_url=redoc_url,  # redoc文档路径
)

# 速率限制（并发限制）
rate_cfg = config.get('API', {}).get('Rate_Limit', {})
max_concurrent = int(rate_cfg.get('Max_Concurrent', 100))
_rate_sem = asyncio.Semaphore(max_concurrent)

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    async with _rate_sem:
        response = await call_next(request)
        return response

# CORS 白名单
cors_cfg = config.get('API', {}).get('CORS', {})
allow_origins = cors_cfg.get('Allow_Origins', ["*"])
allow_methods = cors_cfg.get('Allow_Methods', ["*"])
allow_headers = cors_cfg.get('Allow_Headers', ["*"])
allow_credentials = bool(cors_cfg.get('Allow_Credentials', False))
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=allow_credentials,
    allow_methods=allow_methods,
    allow_headers=allow_headers,
)

# 静态资源：挂载本地 logo 目录到 /logo
logo_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logo')
if os.path.isdir(logo_dir):
    app.mount("/logo", StaticFiles(directory=logo_dir), name="logo")

auth_cfg = config.get('API', {}).get('Auth', {})
auth_enabled = bool(auth_cfg.get('Enabled', False))
auth_header_name = auth_cfg.get('Header_Name', 'X-API-Key')
auth_token = auth_cfg.get('Token', '')
api_key_header = APIKeyHeader(name=auth_header_name, auto_error=False)

def api_auth_dependency(token: str = Security(api_key_header)):
    if not auth_enabled:
        return
    if not token or auth_token == "" or token != auth_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

# API router
if auth_enabled:
    app.include_router(api_router, prefix="/api", dependencies=[Security(api_key_header), Depends(api_auth_dependency)])
else:
    app.include_router(api_router, prefix="/api")

# PyWebIO APP
if config['Web']['PyWebIO_Enable']:
    webapp = asgi_app(lambda: MainView().main_view())
    app.mount("/", webapp)

if __name__ == '__main__':
    uvicorn.run(app, host=Host_IP, port=Host_Port)
