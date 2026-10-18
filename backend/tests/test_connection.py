"""连接层加固测试（p1.2a）。

验证：懒创建引擎/客户端、连接池参数生效、启动预热的重试语义、
预热不杀进程（缺省服务时返回 degraded 报告而非抛异常）。
不真实连接三件套（探活用打桩，避免慢/依赖外部）。
"""
import pytest

from app.core import db, redis_client
from app.core.config import settings
from app.core.startup import _retry_ping, warmup_connections


def test_engine_pool_settings():
    eng = db.get_engine()
    # 懒创建 + 连接池参数来自配置
    assert eng is db.get_engine()          # 单例，不重复建
    assert eng.pool._pre_ping is True      # pool_pre_ping 生效（抗 DB 瞬断）


def test_redis_client_singleton_and_timeout():
    r = redis_client.get_redis()
    assert r is redis_client.get_redis()   # 单例
    assert r.connection_pool.connection_kwargs.get("socket_timeout") == settings.redis_socket_timeout


def test_retry_ping_success_first_try():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return True, None

    ok, detail, attempts = _retry_ping(fn, 3, 0)
    assert ok is True and attempts == 1 and calls["n"] == 1


def test_retry_ping_exhausts_with_backoff():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return False, "down"

    ok, detail, attempts = _retry_ping(fn, 3, 0)  # backoff=0 不让测试慢
    assert ok is False and attempts == 3 and calls["n"] == 3
    assert detail == "down"


def test_warmup_returns_report_not_raise(monkeypatch):
    # 关掉重试退避，保证测试快
    monkeypatch.setattr(settings, "connect_max_retries", 1)
    monkeypatch.setattr(settings, "connect_retry_backoff", 0)
    # 打桩三个 ping，避免真实连接
    monkeypatch.setattr(db, "ping_mysql", lambda: (True, None))
    monkeypatch.setattr(redis_client, "ping_redis", lambda: (True, None))
    from app.core import chroma_client

    monkeypatch.setattr(chroma_client, "ping_chroma", lambda: (False, "chroma down"))
    report = warmup_connections()
    assert report["mysql"]["ok"] is True
    assert report["redis"]["ok"] is True
    assert report["chroma"]["ok"] is False   # chroma 缺失不致命，仅记录
