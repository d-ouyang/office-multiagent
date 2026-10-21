"""模型注册表测试（配置驱动，非硬编码；§十七 + 用户点6）。

验证：
  · /api/v1/models 只返回 in_dialogue=true 的模型；
  · pool 过滤生效（admin 专属模型不泄漏给 default 池）；
  · 逻辑用小模型（embedding/reranker/decision）存在但不在对话列表。
需 pyyaml：pip install pyyaml
"""
from fastapi.testclient import TestClient

from app.core.model_registry import get_dialogue_models, get_logic_model
from app.main import app


def test_models_endpoint_only_dialogue():
    c = TestClient(app)
    r = c.get("/api/v1/models")
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()["models"]]
    # 对话模型在列表里（p6.8 模型列表重构后）
    assert "deepseek-chat" in ids
    assert "deepseek-v4.1-flash-sf" in ids
    assert "glm-5.3-flash-sf" in ids
    # 逻辑小模型绝不进对话列表
    assert "bge-m3" not in ids
    assert "bge-reranker-v2-m3" not in ids
    assert "decision-llm" not in ids


def test_models_pool_filter():
    c = TestClient(app)
    default = c.get("/api/v1/models", params={"pool": "default"}).json()["models"]
    admin = c.get("/api/v1/models", params={"pool": "admin"}).json()["models"]
    default_ids = {m["id"] for m in default}
    admin_ids = {m["id"] for m in admin}
    # deepseek-reasoner（官方 R1）仅 staff/admin 池
    assert "deepseek-reasoner" not in default_ids
    assert "deepseek-reasoner" in admin_ids
    # 每个对话模型带 description（p6.8 前端展示用）
    sample = next(m for m in admin if m["id"] == "deepseek-chat")
    assert sample["description"]
    assert sample["context_window"] > 0


def test_dialogue_models_excludes_logic():
    all_dialogue = get_dialogue_models()
    assert all(m["id"] not in ("bge-m3", "bge-reranker-v2-m3", "decision-llm") for m in all_dialogue)


def test_logic_models_present():
    emb = get_logic_model("embedding")
    rnk = get_logic_model("reranker")
    dec = get_logic_model("decision")
    assert emb is not None and emb.id == "bge-m3"
    assert rnk is not None and rnk.role == "reranker"
    assert dec is not None and dec.role == "decision"
