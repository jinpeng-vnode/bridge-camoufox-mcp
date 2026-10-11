"""浏览器配置目录：临时缓存可删，账号配置要留，磁盘缓存要清。"""

from __future__ import annotations

import glob
import logging
import os
import shutil
import time
import uuid

log = logging.getLogger("bridge")

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_ROOT = os.path.join(ROOT, "browser_cache")
PROFILE_ROOT = os.path.join(ROOT, "browser_profiles")
CACHE_JUNK = ("cache2", "startupCache", "shader-cache", "thumbnails", "OfflineCache")


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
        return ensure_dir(os.path.abspath(user_data_dir))
    if account_id:
        return ensure_dir(os.path.join(PROFILE_ROOT, account_id))
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
