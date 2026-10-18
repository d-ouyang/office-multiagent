"""规划器 + 路由器测试（p3.1，§四.2/§四.3）。

确定性规则打底，故可用固定用例精确断言（不写概率性断言——RAG 铁律）。
"""
from fastapi.testclient import TestClient

from app.core.planner import plan
from app.core.router import decide
from app.main import app


def test_simple_single_intent_low_score():
    p = plan("帮我查一下上个季度的销售汇总")
    assert "rag" in p.intents or "analysis" in p.intents
    d = decide(p)
    assert d.mode == "single"
    assert d.score < d.threshold


def test_multi_step_multi_intent_high_score_routes_multi():
    # 多步骤连接词 + 多意图(分析+报表) + 多输出(excel+pdf) + 依赖词 → 复杂
    text = "先分析销售数据，然后基于分析结果生成报表，同时导出 excel 和 pdf"
    p = plan(text)
    assert p.score >= 3.0
    d = decide(p)
    assert d.mode == "multi"
    # primary_agent 是主意图映射出的【Agent 类型】（办公能力池），不是意图名
    assert d.primary_agent in ("data_analysis", "report_generation")
    assert set(p.intents) >= {"analysis", "report"}


def test_intent_classification_specifics():
    assert "cleaning" in plan("帮我去重并补全缺失值").intents
    assert "visualization" in plan("画一个柱状图看板").intents
    assert "image_restore" in plan("把这张截图的表格还原成数据").intents


def test_signals_are_explainable():
    p = plan("先分析，然后清洗，最后出报表")
    assert set(p.signals) >= {"steps", "intents", "outputs", "length", "dependencies"}
    assert p.signals["steps"]["hits"]  # 命中了步骤连接词


def test_empty_text_general_low_score():
    p = plan("")
    d = decide(p)
    assert p.intents == []
    assert d.mode == "single"
    assert d.primary_agent == "general"


def test_plan_endpoint():
    c = TestClient(app)
    r = c.post("/api/v1/plan", json={"text": "先分析，然后生成 excel 和 pdf 报表"})
    assert r.status_code == 200
    body = r.json()
    assert body["route"] in ("single", "multi")
    assert "score" in body and "reason" in body and "primary_agent" in body
    assert body["route"] == "multi"  # 该用例复杂度高
    assert body["dag"]["subtasks"]  # 复杂任务附带子任务 DAG（p3.2）
