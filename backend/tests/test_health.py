"""集成测试：需 live 服务，默认 skip（防误跑耗时/破坏性操作）。

运行方式（点5 纪律：显式开启，不自动跑）：
    docker compose up -d
    OFFICE_INTEGRATION=1 pytest backend/tests/test_health.py
"""
import os

import pytest

from app.core import chroma_client, db, redis_client
from app.core.config import settings

pytestmark = pytest.mark.skipif(
    os.environ.get("OFFICE_INTEGRATION") != "1",
    reason="需 live 服务；置 OFFICE_INTEGRATION=1 且 docker compose up 后运行",
)


def test_mysql_reachable():
    ok, err = db.ping_mysql()
    assert ok, err


def test_redis_reachable():
    ok, err = redis_client.ping_redis()
    assert ok, err


@pytest.mark.skipif(not settings.require_chroma, reason="REQUIRE_CHROMA=false 时 chroma 可选")
def test_chroma_reachable():
    ok, err = chroma_client.ping_chroma()
    assert ok, err
