#!/usr/bin/env python3
"""配置目录清理：临时缓存可删，账号目录只清磁盘缓存。"""

from __future__ import annotations

import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from profile_util import (  # noqa: E402
    CACHE_ROOT,
    cleanup_ephemeral,
    is_ephemeral,
    profile_dir,
    purge_disk_cache,
    remove_if_ephemeral,
)

failures = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   <- %r" % (extra,)))
    if not cond:
        failures.append(name)


def main() -> int:
    persist = profile_dir("acct1", os.path.join(tempfile.gettempdir(), "account-pool-profile-test"))
    os.makedirs(os.path.join(persist, "cache2"), exist_ok=True)
    os.makedirs(os.path.join(persist, "cookies"), exist_ok=True)
    check("账号目录不是临时缓存", not is_ephemeral(persist), persist)
    removed = purge_disk_cache(persist)
    check("清掉 cache2", "cache2" in removed and not os.path.isdir(os.path.join(persist, "cache2")), removed)
    check("cookie 目录还在", os.path.isdir(os.path.join(persist, "cookies")))
    check("关闭时不删账号目录", remove_if_ephemeral(persist) is False and os.path.isdir(persist))

    old = os.path.join(CACHE_ROOT, "cache_oldtest")
    os.makedirs(old, exist_ok=True)
    os.utime(old, (time.time() - 7200, time.time() - 7200))
    check("临时缓存判定", is_ephemeral(old), old)
    cleaned = cleanup_ephemeral(max_age=3600)
    check("过期临时缓存被清", any(os.path.abspath(p) == os.path.abspath(old) for p in cleaned), cleaned)
    check("过期目录已不在", not os.path.isdir(old))

    if failures:
        print("失败 %d 项" % len(failures))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
