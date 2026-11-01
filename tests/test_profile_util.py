"""配置目录：临时缓存可删，账号目录只清磁盘缓存；路径不能跳出限定的根目录。"""

from __future__ import annotations

import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from profile_util import (  # noqa: E402
    CACHE_ROOT,
    cleanup_ephemeral,
    is_ephemeral,
    profile_dir,
    purge_disk_cache,
    remove_if_ephemeral,
    screenshot_path,
)


@pytest.fixture
def roots(tmp_path, monkeypatch):
    profiles = tmp_path / "profiles"
    shots = tmp_path / "shots"
    profiles.mkdir()
    monkeypatch.setenv("BRIDGE_PROFILE_ROOT", str(profiles))
    monkeypatch.setenv("BRIDGE_SCREENSHOT_ROOT", str(shots))
    return os.path.realpath(profiles), os.path.realpath(shots)


def test_account_dir_keeps_cookies(roots):
    persist = profile_dir("acct1")
    assert os.path.dirname(persist) == roots[0]
    os.makedirs(os.path.join(persist, "cache2"), exist_ok=True)
    os.makedirs(os.path.join(persist, "cookies"), exist_ok=True)
    assert not is_ephemeral(persist)
    assert "cache2" in purge_disk_cache(persist)
    assert not os.path.isdir(os.path.join(persist, "cache2"))
    assert os.path.isdir(os.path.join(persist, "cookies"))
    assert remove_if_ephemeral(persist) is False and os.path.isdir(persist)


def test_user_data_dir_inside_root(roots):
    inside = os.path.join(roots[0], "pool", "acct2")
    assert profile_dir("", inside) == inside
    assert profile_dir("", "pool/acct3") == os.path.join(roots[0], "pool", "acct3")


@pytest.mark.parametrize("bad", ["../escape", "pool/../../escape", "."])
def test_user_data_dir_escape_rejected(roots, bad):
    with pytest.raises(ValueError):
        profile_dir("", bad)


def test_user_data_dir_absolute_outside_rejected(roots, tmp_path):
    with pytest.raises(ValueError):
        profile_dir("", str(tmp_path / "elsewhere"))


@pytest.mark.parametrize("bad", ["../x", "a/b", "a\\b", "..", "x y", "a\x00b", "c:"])
def test_bad_account_id_rejected(roots, bad):
    with pytest.raises(ValueError):
        profile_dir(bad)


def test_screenshot_path(roots, tmp_path):
    assert screenshot_path("a/b.png") == os.path.join(roots[1], "a", "b.png")
    with pytest.raises(ValueError):
        screenshot_path("../../evil.png")
    with pytest.raises(ValueError):
        screenshot_path(str(tmp_path / "evil.png"))


def test_expired_ephemeral_cleaned():
    old = os.path.join(CACHE_ROOT, "cache_oldtest")
    os.makedirs(old, exist_ok=True)
    os.utime(old, (time.time() - 7200, time.time() - 7200))
    assert is_ephemeral(old)
    cleaned = cleanup_ephemeral(max_age=3600)
    assert any(os.path.abspath(p) == os.path.abspath(old) for p in cleaned)
    assert not os.path.isdir(old)
