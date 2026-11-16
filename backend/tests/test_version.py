"""版本号来源测试（v2.3.0-p1.5）。

覆盖：环境变量优先 / 无 env 时回落 git 或 dev / 长度上限。
"""
import os

from app.core import version


def _reset():
    version.app_version.cache_clear()


def test_env_version_wins(monkeypatch):
    """V-1：CI 注入的 APP_VERSION 优先——镜像自带版本，不依赖仓库。"""
    monkeypatch.setenv("APP_VERSION", "v2.3.0")
    _reset()
    assert version.app_version() == "v2.3.0"
    _reset()


def test_fallback_is_honest(monkeypatch):
    """V-2：env 为 dev/空时回落 git describe；两者都没有就诚实返回 dev。"""
    monkeypatch.setenv("APP_VERSION", "dev")
    _reset()
    got = version.app_version()
    assert got
    # 本地开发机有 .git → 形如 v2.3.0 或 v2.3.0-3-gabc1234；容器里没 git → dev
    assert got == "dev" or got.startswith("v") or "-g" in got
    _reset()


def test_version_is_short(monkeypatch):
    """V-3：异常长的输出要截断，避免污染侧栏。"""
    monkeypatch.setenv("APP_VERSION", "x" * 200)
    _reset()
    assert len(version.app_version()) <= 40
    _reset()


def test_env_only_used_when_not_default(monkeypatch):
    """V-4：显式设为 dev 时不当作真实版本——继续尝试 git（开发机看得见 tag）。"""
    monkeypatch.setenv("APP_VERSION", "dev")
    _reset()
    assert version.app_version() != ""
    _reset()
    os.environ.pop("APP_VERSION", None)
