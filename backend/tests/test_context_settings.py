"""v2.3.0-p1.0：上下文阈值热开关测试。

覆盖：观察上限 / 历史渲染上限 / 双协议同源 / 对话轮数 / 设置项暴露。
手法：直接改写 runtime_settings 进程内缓存（不建库），验证"管理端改值 → 下一任务生效"。
"""
import pytest

from app.core import runtime_settings
from app.core.config import settings
from app.orchestration.brain import LlmBrain, history_step_limit
from app.orchestration.memory import prepare_turn
from app.orchestration.react import Step, _summarize_observation


@pytest.fixture()
def rs(monkeypatch):
    """把运行时设置换成内存字典：rs(observation_max_chars=8000) 等价于管理端改过值。"""
    monkeypatch.setattr(runtime_settings, "_loaded", True)
    monkeypatch.setattr(runtime_settings, "_values", {})

    def _set(**kv):
        runtime_settings._values.update({k: str(v) for k, v in kv.items()})

    return _set


def _steps(n: int, chars: int) -> list[Step]:
    return [
        Step(
            thought=f"第{i}步",
            action="read_document",
            action_input={"path": f"{i}.md"},
            observation="字" * chars,
        )
        for i in range(1, n + 1)
    ]


def test_observation_max_chars_from_settings(rs):
    """S-1：单步观察上限取运行时设置，截断如实标注。"""
    rs(observation_max_chars=8000)
    out = _summarize_observation({"content": "字" * 30000, "total_chars": 30000})
    assert "已截断展示" in out
    assert "字" * 8000 in out
    assert "字" * 8001 not in out  # 恰好截在 8000，不多不少


def test_observation_max_chars_zero_means_unlimited(rs):
    """S-1b：填 0 = 不限制（线上出问题时的回退开关）。"""
    rs(observation_max_chars=0)
    body = "字" * 30000
    out = _summarize_observation({"content": body, "total_chars": 30000})
    assert "已截断展示" not in out
    assert body in out


def test_render_history_uses_configured_limit(rs):
    """S-2：ReAct 历史渲染按设置截断（JSON 协议路径）。"""
    rs(history_step_max_chars=8000)
    text = LlmBrain._render_history(_steps(2, 30000))
    assert "已截断" in text
    assert text.count("字") <= 16000
    assert text.count("字") > 14000  # 两步各自截到 8000，不是只留第一步


def test_tool_calls_path_same_limit(rs):
    """S-3：原生 tool_calls 协议与 JSON 协议同源，同一配置值下截断长度一致。"""
    rs(history_step_max_chars=6000)
    msgs = LlmBrain._messages_for_tool_calls("任务", _steps(1, 30000))
    tool_msg = [m for m in msgs if m["role"] == "tool"][0]
    assert len(tool_msg["content"]) == 6000
    assert history_step_limit() == 6000
    assert "…（已截断）" in LlmBrain._render_history(_steps(1, 30000))


def test_recent_rounds_configurable(rs):
    """S-4：对话保留轮数可配；0 表示全部压成摘要（`[:-0]` 空列表陷阱不得复现）。"""
    history = []
    for i in range(5):
        history.append({"role": "user", "content": f"问题{i}"})
        history.append({"role": "assistant", "content": f"回答{i}"})

    rs(history_recent_rounds=2, history_round_chars=80)
    _, parts = prepare_turn(history, "本轮问题")
    assert "问题0" in parts["summary"]
    assert "问题2" in parts["summary"]      # 5 轮里前 3 轮进摘要
    assert "问题3" not in parts["summary"]
    assert "问题3" in parts["recent"]       # 最近 2 轮保留原文
    assert "问题4" in parts["recent"]

    rs(history_recent_rounds=0)
    _, parts0 = prepare_turn(history, "本轮问题")
    assert "recent" not in parts0
    assert "问题4" in parts0["summary"]


def test_round_chars_configurable(rs):
    """S-4b：单轮摘要长度可配（旧实现写死 80）。"""
    rs(history_recent_rounds=0, history_round_chars=20)
    history = [
        {"role": "user", "content": "长" * 200},
        {"role": "assistant", "content": "短" * 200},
    ]
    _, parts = prepare_turn(history, "本轮")
    assert parts["summary"].count("长") == 20
    assert parts["summary"].count("短") == 20


def test_settings_catalog_exposes_new_keys(rs):
    """S-5：四个新键进 catalog，越界值被拒（防管理端写入非法值）。"""
    keys = {i["key"] for i in runtime_settings.public_items()}
    for key in (
        "observation_max_chars",
        "history_step_max_chars",
        "history_recent_rounds",
        "history_round_chars",
    ):
        assert key in keys
    with pytest.raises(ValueError):
        runtime_settings.validate_and_store("history_recent_rounds", 999)
    with pytest.raises(ValueError):
        runtime_settings.validate_and_store("observation_max_chars", -1)


def test_defaults_match_config(rs):
    """S-6：未设值时回落 config（不留 None / 不偷偷改缺省）。"""
    assert runtime_settings.effective("observation_max_chars") == settings.observation_max_chars
    assert runtime_settings.effective("history_step_max_chars") == settings.history_step_max_chars
    assert runtime_settings.effective("history_recent_rounds") == settings.history_recent_rounds
    assert runtime_settings.effective("history_round_chars") == settings.history_round_chars
