"""规划器 + 路由器测试（p3.1，§四.2/§四.3）。

确定性规则打底，故可用固定用例精确断言（不写概率性断言——RAG 铁律）。
"""
from fastapi.testclient import TestClient

from app.core.planner import plan
from app.core.router import decide
from app.main import app


def test_simple_single_intent_low_score():
    # p5.5：「查一下」已从 rag 关键词降级——弱信号词不再单独定路由。
    # 本句无强实体词（订单/销售额/制度…），落 general（全 14 工具兜底）。
    p = plan("帮我查一下上个季度的销售汇总")
    assert p.intents == []
    d = decide(p)
    assert d.mode == "single"
    assert d.primary_agent == "general"
    assert d.score < d.threshold


def test_order_question_no_longer_hijacked_by_rag():
    # p5.5 回归锚点：本地实测事故（2026-11-06）——
    # 「查一下最近10笔订单」曾被 rag 关键词「查一下」劫持进知识库 Agent
    # （工具池无 query_orders）。现在由强实体词「订单」确定性路由。
    p = plan("查一下最近 10 笔订单")
    assert p.intents == ["orders"]
    d = decide(p)
    assert d.mode == "single"
    assert d.primary_agent == "data_analysis"


def test_orders_keywords_cover_transaction_terms():
    for text in ("9月订单数是多少", "退款了多少", "查一下销售额", "本月销量怎么样", "发货明细给我"):
        assert "orders" in plan(text).intents, text


def test_rag_questions_still_route_by_strong_words():
    # 移除「查一下」后，制度/手册/检索类问句靠强词命中 rag。
    assert plan("查一下报销制度").intents[0] == "rag"
    assert plan("检索一下请假制度").intents[0] == "rag"
    assert plan("帮我看看考勤手册").intents[0] == "rag"


def test_orders_covered_by_analysis_and_report():
    # analysis / report 的 Agent 均带 query_orders，orders 副意图不触发误拆。
    p = plan("分析一下订单数据")
    assert set(p.intents) == {"analysis", "orders"}
    d = decide(p)
    assert d.mode == "single"
    assert d.primary_agent == "data_analysis"

    p2 = plan("订单数据导出报表")
    d2 = decide(p2)
    assert d2.mode == "single"


def test_multi_step_multi_intent_high_score_routes_multi():
    # 知识库口径 → 数据分析是真实跨能力交接，应走 multi。
    text = "先查一下报销制度，然后基于这个制度分析销售数据"
    p = plan(text)
    assert p.score >= 3.0
    d = decide(p)
    assert d.mode == "multi"
    # primary_agent 是主意图映射出的【Agent 类型】（办公能力池），不是意图名
    assert d.primary_agent in ("data_analysis", "rag_retrieval")
    assert set(p.intents) >= {"analysis", "rag"}


def test_analysis_report_chart_are_covered_by_one_agent():
    p = plan("先分析销售数据，然后生成报表，同时导出 pdf 和图表")
    assert p.score >= 3.0
    d = decide(p)
    assert d.mode == "single"
    assert "已覆盖" in d.reason


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
    assert body["route"] == "single"  # 一个报表/分析 Agent 已覆盖导出与图表
