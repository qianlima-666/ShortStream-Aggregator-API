import os

import yaml
from fastapi import APIRouter

from app.api.models.APIResponseModel import iOS_Shortcut

# 读取项目根目录下的集中配置文件 config/config.yaml
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
config_path = os.path.join(_root, "config", "config.yaml")
with open(config_path, "r", encoding="utf-8") as file:
    config = yaml.safe_load(file)

router = APIRouter()


@router.get(
    "/shortcut",
    response_model=iOS_Shortcut,
    summary="用于iOS快捷指令的版本更新信息/Version update information for iOS shortcuts",
)
async def get_shortcut():
    """
    @desc 获取 iOS 快捷指令最新版本和说明
    @returns iOS_Shortcut 返回包含版本、更新时间、说明和下载链接
    """
    shortcut_config = config["iOS_Shortcut"]
    version = shortcut_config["iOS_Shortcut_Version"]
    update = shortcut_config["iOS_Shortcut_Update_Time"]
    link = shortcut_config["iOS_Shortcut_Link"]
    link_en = shortcut_config["iOS_Shortcut_Link_EN"]
    note = shortcut_config["iOS_Shortcut_Update_Note"]
    note_en = shortcut_config["iOS_Shortcut_Update_Note_EN"]
    return iOS_Shortcut(version=str(version), update=update, link=link, link_en=link_en, note=note, note_en=note_en)
