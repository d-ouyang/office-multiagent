"""v2.3.0-p1.3：意图路由三处修正的回归测试。

背景（2026-11-16 真链路冒烟）：提示「不要检索知识库。请直接读取文档文件 smoke-long.md」
被规则判成 rag（否定词不处理）→ 路由到工具池没有 read_document 的知识库 Agent
→ 模型只能反问"请上传文件"，而文件就在用户目录里。

三条修正各锁一组用例：
  1. 否定窗口：被否定的关键词不计分，但正常表述不受影响；
  2. 能力预检扩表：文件读取类词 → read_document，缺该工具的 Agent 改道 general；
  3. 决策模型标签：读文件归 general（提示词层，单测覆盖不到 LLM，只锁规则不回归）。
"""
import pytest

from app.core import planner, router
from app.core.planner import plan
from app.core.router import decide


@pytest.fixture(autouse=True)
def _fresh_config():
    """planner.yaml / agents.yaml 都是 lru_cache，改了配置必须清缓存再断言。"""
    planner.load_planner_config.cache_clear()
    router._agent_tool_pools.cache_clear()
    yield
    planner.load_planner_config.cache_clear()
    router._agent_tool_pools.cache_clear()


def test_negated_rag_keywords_not_counted():
    """N-1：「不要检索知识库」不再把任务推进 rag（真跑事故原句）。"""
    p = plan("不要检索知识库。请直接读取文档文件 smoke-long.md，逐章列出金额上限")
    assert "rag" not in p.intents


def test_negation_does_not_swallow_normal_question():
    """N-2：否定窗口不能误伤正常问句——「别」以外的肯定表述照常命中。"""
    assert "rag" in plan("查一下差旅报销制度").intents
    assert "rag" in plan("公司手册里怎么规定").intents


def test_postposed_negation_still_counts():
    """N-3：只看前置窗口——「检索不到」是结果描述，仍算检索需求。"""
    p = plan("知识库检索不到就直接说，不要编造")
    assert "rag" in p.intents


def test_file_read_reroutes_rag_agent_to_general():
    """N-4：文本要求读文件、而知识库 Agent 没有 read_document → 改道 general。"""
    d = decide(plan("检索知识库并读取文件 a.md 的内容"))
    assert d.primary_agent == "general"
    assert "改道 general" in d.reason


def test_file_read_reroutes_analysis_agent_to_general():
    """N-5：数据分析 Agent 同样没有 read_document，读文件类任务也要改道。"""
    d = decide(plan("统计分析并读取文档 upload.xlsx 里的字段"))
    assert d.primary_agent == "general"


def test_pure_kb_question_keeps_rag_agent():
    """N-6：纯知识库问句不误伤——仍走 rag_retrieval。"""
    d = decide(plan("差旅报销制度是怎么规定的"))
    assert d.primary_agent == "rag_retrieval"


def test_generate_document_not_rerouted():
    """N-7：组合词不误伤——「生成周报文档」仍归报表 Agent（guards 里没有裸「文档」）。"""
    d = decide(plan("帮我生成一份周报文档"))
    assert d.primary_agent == "report_generation"
