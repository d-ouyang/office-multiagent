"""显式长期记忆（p6.29）——repo / 工具 / 注入块 / API 四层。"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.core import user_memory_repo
from app.core.config import settings
from app.core.user_memory_repo import MemoryFull, UserMemoryRepo
from app.main import app


@pytest.fixture
def eng(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with engine.begin() as c:
        c.execute(text("CREATE TABLE `user` (id INTEGER PRIMARY KEY, employee_id TEXT, username TEXT, role TEXT, model_pool_id INTEGER, token_version INTEGER NOT NULL DEFAULT 0, password_hash TEXT)"))
        c.execute(text("CREATE TABLE user_memory (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, content TEXT NOT NULL, source TEXT DEFAULT 'agent', created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role) VALUES (1, 'EMP001', 'dev', 'admin')"))
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role) VALUES (2, 'EMP002', 'chen', 'user')"))
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-memory")
    for mod in ("app.core.db", "app.core.identity", "app.core.session_repo", "app.core.user_memory_repo"):
        monkeypatch.setattr(f"{mod}.get_engine", lambda: engine)
    return engine


def _auth(emp: str = "EMP001") -> dict[str, str]:
    import jwt as pyjwt

    token = pyjwt.encode({"sub": emp, "tv": 0}, "test-secret-memory", algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# 仓储层
# --------------------------------------------------------------------------- #

def test_add_list_delete(eng):
    repo = UserMemoryRepo(eng)
    row = repo.add(1, "报销口径以财务制度 2026 版为准")
    assert row["duplicated"] is False and row["id"] > 0
    assert repo.count(1) == 1
    rows = repo.list_for(1)
    assert rows[0]["content"] == "报销口径以财务制度 2026 版为准"
    assert rows[0]["source"] == "agent"
    assert repo.delete(1, row["id"]) is True
    assert repo.count(1) == 0


def test_dedupe_identical_content(eng):
    repo = UserMemoryRepo(eng)
    first = repo.add(1, "喜欢简洁的回复")
    again = repo.add(1, "喜欢简洁的回复")
    assert again["duplicated"] is True and again["id"] == first["id"]
    assert repo.count(1) == 1


def test_empty_rejected(eng):
    repo = UserMemoryRepo(eng)
    with pytest.raises(ValueError):
        repo.add(1, "   ")


def test_content_too_long(eng, monkeypatch):
    monkeypatch.setattr(settings, "user_memory_content_chars", 10)
    repo = UserMemoryRepo(eng)
    with pytest.raises(user_memory_repo.ContentTooLong):
        repo.add(1, "x" * 11)


def test_memory_full_rejects_noisy_eviction(eng, monkeypatch):
    """满了如实拒绝——不静默淘汰最旧的。"""
    monkeypatch.setattr(settings, "user_memory_max_items", 2)
    repo = UserMemoryRepo(eng)
    repo.add(1, "记忆一")
    repo.add(1, "记忆二")
    with pytest.raises(MemoryFull):
        repo.add(1, "记忆三")
    assert repo.count(1) == 2


def test_keyword_search_and_isolation(eng):
    repo = UserMemoryRepo(eng)
    repo.add(1, "报销口径以财务制度为准")
    repo.add(1, "喜欢简洁的回复")
    repo.add(2, "别人的记忆")
    assert len(repo.list_for(1, keyword="报销")) == 1
    assert len(repo.list_for(1)) == 2
    assert len(repo.list_for(2)) == 1


def test_delete_owner_enforced(eng):
    """删除别人的记忆返回 False（越权与 404 同形）。"""
    repo = UserMemoryRepo(eng)
    row = repo.add(2, "chen 的记忆")
    assert repo.delete(1, row["id"]) is False
    assert repo.count(2) == 1


# --------------------------------------------------------------------------- #
# 工具层（remember / recall）
# --------------------------------------------------------------------------- #

def test_remember_recall_tools(eng):
    from app.orchestration.tools import ToolRegistry
    from app.orchestration.tools_memory import register_memory_tools

    reg = ToolRegistry()
    register_memory_tools(reg, UserMemoryRepo(eng), 1)
    assert set(reg.names()) >= {"remember", "recall"}

    saved = reg.call("remember", content="报销口径以财务制度为准")
    assert saved.ok and saved.output["saved"] is True

    dup = reg.call("remember", content="报销口径以财务制度为准")
    assert dup.ok and "未重复写入" in dup.output["message"]

    # 工具描述必须带"只有用户明确要求记住时才调用"约束（提示词护栏，防偷偷记）
    desc = next(d["description"] for d in reg.describe() if d["name"] == "remember")
    assert "明确要求记住" in desc

    found = reg.call("recall", keyword="报销")
    assert found.ok and found.output["count"] == 1 and found.output["total"] == 1

    miss = reg.call("recall", keyword="不存在")
    assert miss.ok and miss.output["count"] == 0
    assert "没有命中" in miss.output["note"]

    all_rows = reg.call("recall")
    assert all_rows.ok and all_rows.output["count"] == 1


# --------------------------------------------------------------------------- #
# 注入块
# --------------------------------------------------------------------------- #

def test_user_memory_block_and_context_items():
    from app.orchestration.memory import context_items, user_memory_block

    mems = [{"content": "喜欢简洁的回复"}, {"content": "报销以财务制度为准"}]
    block = user_memory_block(mems)
    assert "【用户长期记忆】" in block
    assert "- 喜欢简洁的回复" in block

    long = [{"content": "x" * 2000}]
    assert "已截断" in user_memory_block(long, max_chars=100)

    items = context_items({"memory": "- 记忆内容", "current": "问题"})
    assert any(i["key"] == "memory" and i["tokens"] > 0 for i in items)
    items2 = context_items({"current": "问题"})
    assert not any(i["key"] == "memory" for i in items2)


# --------------------------------------------------------------------------- #
# API 层
# --------------------------------------------------------------------------- #

def test_api_memory_crud(eng):
    client = TestClient(app)

    # 未登录 401
    assert client.get("/api/v1/memory").status_code == 401

    r = client.post("/api/v1/memory", json={"content": "喜欢简洁的回复"}, headers=_auth())
    assert r.status_code == 200
    mid = r.json()["id"]
    assert r.json()["source"] == "user"

    r2 = client.get("/api/v1/memory", headers=_auth())
    assert r2.status_code == 200 and r2.json()["total"] == 1

    # 重复添加不报错（幂等）
    r3 = client.post("/api/v1/memory", json={"content": "喜欢简洁的回复"}, headers=_auth())
    assert r3.status_code == 200

    # 空内容 400 / 超长 400
    assert client.post("/api/v1/memory", json={"content": "  "}, headers=_auth()).status_code == 400
    assert (
        client.post("/api/v1/memory", json={"content": "x" * 301}, headers=_auth()).status_code == 400
    )

    # chen 删 dev 的记忆 → 404；dev 自己删 → 200
    assert client.delete(f"/api/v1/memory/{mid}", headers=_auth("EMP002")).status_code == 404
    assert client.delete("/api/v1/memory/99999", headers=_auth()).status_code == 404
    assert client.delete(f"/api/v1/memory/{mid}", headers=_auth()).status_code == 200
    assert client.get("/api/v1/memory", headers=_auth()).json()["total"] == 0


def test_api_memory_full_409(eng, monkeypatch):
    monkeypatch.setattr(settings, "user_memory_max_items", 1)
    client = TestClient(app)
    assert client.post("/api/v1/memory", json={"content": "第一条"}, headers=_auth()).status_code == 200
    r = client.post("/api/v1/memory", json={"content": "第二条"}, headers=_auth())
    assert r.status_code == 409 and "已满" in r.json()["detail"]["message"]


def test_registry_only_when_user_id(eng):
    """匿名场景（user_id=None）不挂记忆工具——工具不可见=能力缺失，不猜。"""
    from app.orchestration.agents import build_default_registry

    reg = build_default_registry(eng, username="dev", user_id=None)
    assert not reg.has("remember") and not reg.has("recall")
    reg2 = build_default_registry(eng, username="dev", user_id=1)
    assert reg2.has("remember") and reg2.has("recall")
