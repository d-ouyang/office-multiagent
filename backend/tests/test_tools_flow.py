"""render_flow：只校验结构，不收坐标。"""
from app.core.events import EventType, RunEventEmitter
from app.orchestration.react import Step, run_react
from app.orchestration.tools import ToolRegistry
from app.orchestration.tools_flow import render_flow


class _Once:
    def __init__(self, step: Step) -> None:
        self.step = step
        self.usage = {"total_tokens": 0}

    def next_step(self, task: str, history: list[Step]) -> Step:
        if history:
            return Step(final="流程图已给出。")
        return self.step


def test_render_flow_normalizes_path_and_rejects_unknown_node():
    out = render_flow(
        title="报销",
        nodes=[
            {"id": "submit", "label": "提交", "kind": "rect", "lane": "blue"},
            {"id": "check", "label": "超限?", "kind": "diamond", "lane": "amber"},
            {"id": "boss", "label": "加签", "kind": "rect", "lane": "red"},
        ],
        edges=[
            {"from": "submit", "to": "check"},
            {"from": "check", "to": "boss", "label": "是"},
        ],
        path=["submit", "check"],
    )
    assert out["visual"]["kind"] == "flow"
    assert out["visual"]["path"] == ["submit", "check"]
    assert "boss" not in out["visual"]["path"]
    bad = render_flow(nodes=[{"id": "a", "label": "甲"}], edges=[{"from": "a", "to": "missing"}], path=["a"])
    assert "不存在" in bad["error"]


def test_flow_emits_visual_event():
    reg = ToolRegistry()
    reg.register("render_flow", render_flow, description="flow")
    emitter = RunEventEmitter("run", "turn")
    events = []
    run_react(
        "画流程",
        _Once(Step(action="render_flow", action_input={
            "title": "报销",
            "nodes": [{"id": "a", "label": "提交"}],
            "edges": [],
            "path": ["a"],
        })),
        reg,
        emitter=emitter,
        emit=events.append,
    )
    visual = [ev for ev in events if ev.type == EventType.VISUAL]
    assert len(visual) == 1
    assert visual[0].data["kind"] == "flow"
    assert visual[0].data["payload"]["path"] == ["a"]
