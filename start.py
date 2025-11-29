import os
import shutil
import uvicorn

from crawlers.utils.logger import logger

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

yaml = YAML()
yaml.preserve_quotes = True


# ----------------------------------------------
# 辅助判断
# ----------------------------------------------

def is_list(x):
    return isinstance(x, list) or isinstance(x, CommentedSeq)


def is_dict(x):
    return isinstance(x, dict) or isinstance(x, CommentedMap)


# ============================================================
# =============== AllowedDomains 合并逻辑 ====================
# ============================================================

def merge_domain_list(template_list, config_list, path):
    """
    规则：
    - 保留 config 的原有值
    - 模板新增 → 追加
    - 去重
    - 顺序为：config 原顺序 + 模板新增
    """
    original = list(config_list)
    added = []

    for item in template_list:
        if item not in config_list:
            config_list.append(item)
            added.append(item)

    if added:
        logger.info(f"[AllowedDomains] 新增条目 path={path}: {added}")

    for item in original:
        logger.info(f"[AllowedDomains] 保留原有条目 path={path}: {item}")


# ============================================================
# =============== iOS_Shortcut 强一致同步 ===================
# ============================================================

def sync_ios_shortcut(template, config, path):
    """
    iOS_Shortcut 强一致同步：
    - 删除模板没有的 key
    - 模板有的 key 必须存在
    - 仅当值不同时才覆盖
    """

    # ② 遍历模板项
    for key, t_val in template.items():
        cur_path = f"{path}.{key}"

        # 模板有，config 没有 → 新增
        if key not in config:
            config[key] = t_val
            logger.info(f"[iOS_Shortcut] 新增 key: {cur_path} = {t_val}")
            continue

        c_val = config[key]

        # dict → 递归处理
        if is_dict(t_val) and is_dict(c_val):
            sync_ios_shortcut(t_val, c_val, cur_path)
            continue

        # list → 完全强覆盖（但相同不覆盖）
        if is_list(t_val) and is_list(c_val):
            if t_val != c_val:
                logger.info(f"[iOS_Shortcut] 覆盖列表: {cur_path}")
                config[key] = t_val
            else:
                logger.debug(f"[iOS_Shortcut] 保留列表: {cur_path}（值相同）")
            continue

        # 普通值 → 仅值不同才覆盖
        if t_val != c_val:
            logger.info(f"[iOS_Shortcut] 覆盖值: {cur_path}: {c_val} -> {t_val}")
            config[key] = t_val
        else:
            logger.debug(f"[iOS_Shortcut] 保留值: {cur_path} = {c_val}（值相同）")

    # ① 删除多余 key
    for key in list(config.keys()):
        if key not in template:
            logger.info(f"[iOS_Shortcut] 删除多余 key: {path}.{key}")
            del config[key]


# ============================================================
# ================= 普通字典强一致同步 =======================
# ============================================================

def strict_sync(template, config, path):
    """
    普通字段：严格同步 key，但保留原 value
    """

    # 新增缺失 key
    for key, value in template.items():
        if key not in config:
            config[key] = value
            logger.info(f"[ADD] 新增 key: {path}.{key}")

        else:
            # 递归处理字典
            if is_dict(value) and is_dict(config[key]):
                strict_sync(value, config[key], f"{path}.{key}")
    
    # 删除多余 key
    for key in list(config.keys()):
        if key not in template:
            logger.info(f"[DEL] 删除多余 key: {path}.{key}")
            del config[key]


# ============================================================
# =============== 主同步规则入口（含特例处理） ===============
# ============================================================

def sync_with_rules(template, config, path="root"):
    """
    总调度器：按你的规则执行
    """

    # --- API.Version & API.Update_Time：仅这两个字段强制覆盖 ---
    if path == "root.API":
        force_keys = ["Version", "Update_Time"]

        for key, t_val in template.items():

            # 这两个字段：值不同才覆盖
            if key in force_keys:
                old_val = config.get(key)

                if old_val != t_val:
                    logger.info(f"[API 覆盖] {path}.{key}: {old_val} -> {t_val}")
                    config[key] = t_val
                else:
                    logger.debug(f"[API 保留] {path}.{key} = {t_val}（值相同）")

            else:
                # 其他 API 字段遵循普通 strict 同步规则：值保留，不覆盖
                if key not in config:
                    logger.info(f"[API 新增普通字段] {path}.{key}")
                    config[key] = t_val
                else:
                    logger.debug(f"[API 保留普通字段] {path}.{key}")

        # 删除 API 中模板不存在的 key
        for key in list(config.keys()):
            if key not in template:
                logger.info(f"[API 删除多余字段] {path}.{key}")
                del config[key]

        return

    # --- iOS_Shortcut 强一致（值覆盖 + key 一致） ---
    if path == "root.iOS_Shortcut":
        sync_ios_shortcut(template, config, path)
        return

    # --- AllowedDomains：列表按特殊合并策略 ---
    if path.startswith("root.AllowedDomains"):
        for key, t_val in template.items():
            new_path = f"{path}.{key}"

            if key not in config:
                config[key] = t_val
                logger.info(f"[AllowedDomains] 新增字段: {new_path}")
                continue

            if is_list(t_val) and is_list(config[key]):
                merge_domain_list(t_val, config[key], new_path)
                continue

            # 递归处理
            if is_dict(t_val) and is_dict(config[key]):
                sync_with_rules(t_val, config[key], new_path)
        return

    # --- 默认：普通字典严格同步 key（保留原值） ---
    strict_sync(template, config, path)

    # 子节点递归
    for key, t_val in template.items():
        if is_dict(t_val) and is_dict(config.get(key)):
            sync_with_rules(t_val, config[key], f"{path}.{key}")


# ============================================================
# =================== 文件级同步入口 =========================
# ============================================================

def sync_file(template_path, config_path):
    logger.info(f"================== 同步文件 ==================")
    logger.info(f"模板: {template_path}")
    logger.info(f"配置: {config_path}")

    template = yaml.load(open(template_path, "r", encoding="utf-8"))
    config = yaml.load(open(config_path, "r", encoding="utf-8"))

    sync_with_rules(template, config)

    yaml.dump(config, open(config_path, "w", encoding="utf-8"))
    logger.info(f"==> 同步完成: {config_path}\n")


# ============================================================
# ==================== 主流程 ===============================
# ============================================================

def ensure_config_examples_copied():
    # 确保 config 目录存在
    os.makedirs("config", exist_ok=True)

    # 复制缺失文件
    for file in os.listdir("config.example"):
        src = os.path.join("config.example", file)
        if not os.path.isfile(src):
            continue
        dst = os.path.join("config", file)
        if not os.path.exists(dst):
            shutil.copy(src, dst)
            logger.info(f"复制 {file} 到 config 文件夹")

    # 对每个文件执行同步
    for file in os.listdir("config.example"):
        template_path = os.path.join("config.example", file)
        config_path = os.path.join("config", file)
        if os.path.isfile(template_path):
            sync_file(template_path, config_path)


if __name__ == "__main__":
    ensure_config_examples_copied()
    from app.main import Host_IP, Host_Port
    uvicorn.run("app.main:app", host=Host_IP, port=Host_Port, reload=False, log_level="info")
