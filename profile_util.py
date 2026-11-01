"""浏览器配置目录：临时缓存可删，账号配置要留，磁盘缓存要清。"""

from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import time
import uuid

log = logging.getLogger("bridge")

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_ROOT = os.path.join(ROOT, "browser_cache")
DEFAULT_PROFILE_ROOT = os.path.join(ROOT, "browser_profiles")
DEFAULT_SCREENSHOT_ROOT = os.path.join(ROOT, "screenshots")
CACHE_JUNK = ("cache2", "startupCache", "shader-cache", "thumbnails", "OfflineCache")
ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def profile_root() -> str:
    """按账号保留的配置目录都必须在这个根目录下（BRIDGE_PROFILE_ROOT）。"""
    return os.path.realpath(os.environ.get("BRIDGE_PROFILE_ROOT") or DEFAULT_PROFILE_ROOT)


def screenshot_root() -> str:
    """截图只能写到这个根目录下（BRIDGE_SCREENSHOT_ROOT）。"""
    return os.path.realpath(os.environ.get("BRIDGE_SCREENSHOT_ROOT") or DEFAULT_SCREENSHOT_ROOT)


def confine(path: str, root: str) -> str:
    """把路径规范化（相对路径按 root 解析，跟随符号链接），跳出 root 就拒绝。"""
    if not path or "\x00" in path:
        raise ValueError("路径为空或不合法")
    full = os.path.realpath(os.path.join(root, path))
    try:
        inside = os.path.commonpath([root, full]) == root
    except ValueError:
        inside = False
    if not inside or full == root:
        raise ValueError("路径不在允许的目录 %s 下：%s" % (root, path[:200]))
    return full


def check_account_id(account_id: str) -> str:
    if not ACCOUNT_ID_RE.match(account_id) or set(account_id) == {"."}:
        raise ValueError("account_id 只允许字母、数字、下划线、点、横线：%s" % account_id[:200])
    return account_id


def screenshot_path(path: str) -> str:
    full = confine(path, screenshot_root())
    ensure_dir(os.path.dirname(full))
    return full


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def create_ephemeral_cache() -> str:
    ensure_dir(CACHE_ROOT)
    cleanup_ephemeral()
    cache_id = uuid.uuid4().hex[:8]
    path = os.path.join(CACHE_ROOT, "cache_%s" % cache_id)
    os.makedirs(path, exist_ok=True)
    log.info("已创建临时缓存目录: %s", path)
    return path


def profile_dir(account_id: str, user_data_dir: str = "") -> str:
    if user_data_dir:
        return ensure_dir(confine(user_data_dir, profile_root()))
    if account_id:
        return ensure_dir(confine(check_account_id(account_id), profile_root()))
    return create_ephemeral_cache()


def is_ephemeral(path: str) -> bool:
    if not path:
        return False
    try:
        norm = os.path.abspath(path)
        root = os.path.abspath(CACHE_ROOT)
        return os.path.commonpath([root, norm]) == root
    except ValueError:
        return False


def purge_disk_cache(profile_dir_path: str) -> list[str]:
    removed = []
    if not profile_dir_path or not os.path.isdir(profile_dir_path):
        return removed
    for name in CACHE_JUNK:
        path = os.path.join(profile_dir_path, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            removed.append(name)
            log.info("已清理磁盘缓存: %s", path)
    return removed


def cleanup_ephemeral(max_age: int = 3600) -> list[str]:
    removed = []
    if not os.path.isdir(CACHE_ROOT):
        return removed
    for old in glob.glob(os.path.join(CACHE_ROOT, "cache_*")):
        if not os.path.isdir(old):
            continue
        age = time.time() - os.path.getmtime(old)
        if age > max_age:
            shutil.rmtree(old, ignore_errors=True)
            removed.append(old)
            log.info("已清理过期临时缓存: %s", os.path.basename(old))
    return removed


def remove_if_ephemeral(path: str) -> bool:
    if is_ephemeral(path) and os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
        log.info("已删除临时缓存: %s", path)
        return True
    if path:
        purge_disk_cache(path)
    return False
