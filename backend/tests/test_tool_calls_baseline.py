"""v2.0.0-p1.0：tool_calls golden 与 NDJSON 事件契约冻结。"""
import json
from pathlib import Path

import pytest

from app.core.events import EventType
from app.core.model_registry import load_registry

GOLDEN = json.loads(
    (Path(__file__).parent / "golden" / "tool_calls_cases.json").read_text(encoding="utf-8")
)
FROZEN_TOOL_PATH_EVENTS = {
    "content_delta",
    "tool_call_start",
    "tool_call_end",
    "observation",
    "done",
}


def test_golden_cases_cover_six_protocol_paths():
    assert {case["id"] for case in GOLDEN} == {
        "single_tool", "multiple_tools", "missing_arguments",
        "unknown_tool", "final_only", "stream_final",
    }
    assert len(GOLDEN) == 6


@pytest.mark.parametrize("case", GOLDEN, ids=lambda case: case["id"])
def test_golden_events_are_in_frozen_ndjson_contract(case):
    assert case["expected_events"]
    assert set(case["expected_events"]) <= FROZEN_TOOL_PATH_EVENTS
    assert {event.value for event in EventType} >= FROZEN_TOOL_PATH_EVENTS


def test_dialogue_models_have_explicit_probed_tool_capability():
    dialogue = [m for m in load_registry()["models"] if m.in_dialogue and m.enabled]
    assert dialogue
    # 新对话模型未点测时为 None，本护栏会迫使先补能力表，再进入 auto 灰度。
    assert all(isinstance(m.supports_tools, bool) for m in dialogue)


def test_every_tool_call_has_stable_id_and_json_arguments():
    for case in GOLDEN:
        for call in case["response"].get("tool_calls", []):
            assert call["id"]
            assert call["function"]["name"]
            assert isinstance(json.loads(call["function"]["arguments"]), dict)
