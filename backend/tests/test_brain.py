"""Brain 测试（p5.1a）——假 chat（不真调云端）；坏输出如实停止，绝不编造。"""
import pytest

from app.core.config import settings
from app.core.llm import LlmError, LlmResult
from app.orchestration.brain import LlmBrain, extract_json, make_brain
from app.orchestration.react import Step, StubBrain
from app.orchestration.tools import ToolRegistry


class FakeChat:
    def __init__(self, outputs: list[str], fail: bool = False):
        self.outputs = list(outputs)
        self.fail = fail
        self.calls: list[list[dict]] = []

    def __call__(self, model_id: str, messages: list[dict], **kw) -> LlmResult:
        self.calls.append(messages)
        if self.fail:
            raise LlmError("模拟断网")
        return LlmResult(
            content=self.outputs.pop(0), prompt_tokens=10, completion_tokens=5, total_tokens=15,
            model=model_id,
        )


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register("db_query", lambda sql: {}, description="查询业务库")
    reg.register("rag_retrieve", lambda query: {}, description="检索知识库")
    return reg


def test_extract_json_variants():
    assert extract_json('{"a":1}') == {"a": 1}
    assert extract_json('前言```json\n{"a":1}\n```后记') == {"a": 1}
    assert extract_json('模型说：{"a": 1} 完毕') == {"a": 1}
    assert extract_json("完全不是 JSON") is None


def test_llm_brain_action_step():
    chat = FakeChat(['{"thought":"查库","action":"db_query","action_input":{"sql":"SELECT 1"}}'])
    brain = LlmBrain(model_id="deepseek-chat", tools=_registry(), chat_fn=chat)
    step = brain.next_step("任务", [])
    assert step.action == "db_query"
    assert step.action_input == {"sql": "SELECT 1"}
    assert step.final is None
    # 提示词里带工具清单（Brain 知道有哪些能力）
    assert "db_query" in chat.calls[0][0]["content"]


def test_llm_brain_final_step():
    chat = FakeChat(['{"thought":"完成","final":"答案是 5 天"}'])
    brain = LlmBrain(model_id="deepseek-chat", tools=_registry(), chat_fn=chat)
    step = brain.next_step("任务", [])
    assert step.final == "答案是 5 天"


def test_llm_brain_bad_json_stops_honestly():
    chat = FakeChat(["我觉觉得应该查一下（不是 JSON）"])
    brain = LlmBrain(model_id="deepseek-chat", tools=_registry(), chat_fn=chat)
    step = brain.next_step("任务", [])
    assert step.final is not None and "无法解析" in step.final
    assert step.action is None  # 不猜动作、不编数据


def test_llm_brain_llm_error_stops_honestly():
    chat = FakeChat([], fail=True)
    brain = LlmBrain(model_id="deepseek-chat", tools=_registry(), chat_fn=chat)
    step = brain.next_step("任务", [])
    assert step.final is not None and "模型暂不可用" in step.final


def test_llm_brain_usage_accumulates():
    chat = FakeChat([
        '{"thought":"t1","action":"db_query","action_input":{}}',
        '{"thought":"t2","final":"done"}',
    ])
    brain = LlmBrain(model_id="deepseek-chat", tools=_registry(), chat_fn=chat)
    brain.next_step("任务", [])
    brain.next_step("任务", [Step(thought="t1", action="db_query", observation="{}")])
    assert brain.usage["calls"] == 2
    assert brain.usage["total_tokens"] == 30  # 15 × 2


def test_llm_brain_custom_system_prompt_injected():
    # p5.1b：AgentSpec 角色指令注入；JSON 协议仍由 brain 统一保证
    chat = FakeChat(['{"thought":"t","final":"ok"}'])
    brain = LlmBrain(
        model_id="deepseek-chat", tools=_registry(), chat_fn=chat,
        system_prompt="你是知识库问答 Agent。绝不编造制度条文。",
    )
    brain.next_step("任务", [])
    system = chat.calls[0][0]["content"]
    assert "知识库问答 Agent" in system
    assert "只能输出一个 JSON" in system
    assert "db_query" in system


def test_make_brain_falls_back_to_stub_without_key(monkeypatch):
    monkeypatch.setattr(settings, "llm_brain_model", "deepseek-chat")
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    monkeypatch.setattr(settings, "siliconflow_api_key", "")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    brain = make_brain(_registry(), fallback_answer="[x] 处理完成")
    assert isinstance(brain, StubBrain)
    assert brain.next_step("t", []).final == "[x] 处理完成"  # 基线行为不变


def test_make_brain_uses_llm_when_key_present(monkeypatch):
    monkeypatch.setattr(settings, "llm_brain_model", "deepseek-chat")
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    brain = make_brain(_registry())
    assert isinstance(brain, LlmBrain)
