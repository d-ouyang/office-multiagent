"""2.1.0 P1-1 HITL：ask_user 暂停 → 前端补充 → Command(resume) 断点续跑。

流程实测要点：
- ask_user sentinel → single_node 返回 need_input → ask_pause 节点 interrupt() 落 checkpoint；
- resume 注入回答后回到 single_node，已完成步骤以观察回放进上下文（副作用零重跑）；
- multi（allow_ask_user=False）下 ask_user 不暂停，给替代观察继续循环。
"""
from langgraph.checkpoint.memory import MemorySaver

from app.orchestration import graph as gmod
from app.orchestration.graph import build_graph, run_react
from app.orchestration.react import Step
from app.orchestration.tools_ask import make_ask_user_tool


class ScriptedBrain:
    """脚本 brain：第一轮调 ask_user，收到用户补充后给终答。"""

    def __init__(self) -> None:
        self.usage: dict = {}
        self.rounds = 0

    def next_step(self, task: str, history: list[Step]) -> Step:
        self.rounds += 1
        seeded = any("用户已补充输入" in (s.observation or "") for s in history)
        if not seeded:
            return Step(
                thought="缺数据，问用户要文件",
                calls=[
                    {
                        "name": "ask_user",
                        "arguments": {
                            "question": "需要上传销售数据文件（csv/xlsx），数据库里没有你要清洗的那份",
                            "need_file": True,
                            "file_hint": "带表头的 csv",
                        },
                        "id": "c1",
                    }
                ],
            )
        return Step(final="已收到补充文件，清洗完成：去重 2 行、补全 5 个缺失值。")


def test_ask_user_pause_then_resume_continues_from_replay(monkeypatch):
    brain = ScriptedBrain()
    monkeypatch.setattr(gmod, "make_brain", lambda *a, **k: brain)

    events: list = []
    emitter = gmod.RunEventEmitter("t-hitl", "t-hitl")
    graph = build_graph(
        emitter,
        lambda ev: events.append(ev),
        token_pool=None,
        checkpointer=MemorySaver(),
    )
    cfg = {"configurable": {"thread_id": "t-hitl"}}
    init = {
        "text": "清洗我的销售数据并出报告",
        "run_id": "t-hitl",
        "turn_id": "t-hitl",
        "model": None,
        "effort": None,
        "context_parts": {"current": "清洗我的销售数据并出报告"},
    }
    state = graph.invoke(init, cfg)

    # 暂停：interrupt 携带 ask_user 载荷，need_input 落 state
    assert state["__interrupt__"][0].value["type"] == "ask_user"
    qs = state["need_input"]["questions"]
    assert len(qs) == 1 and qs[0]["need_file"] is True
    assert "销售数据" in qs[0]["question"]
    assert state["react_history"], "已完成步骤应序列化供回放"
    ask_events = [e for e in events if e.type.value == "ask_user"]
    assert len(ask_events) == 1

    # resume：注入用户回答 → 回到 single_node → 基于回放 + 补充给终答
    state2 = graph.invoke(gmod.Command(resume="已经上传 sales.csv"), cfg)
    assert not state2.get("need_input")
    assert "清洗完成" in str(state2.get("result"))
    # 副作用零重跑：brain 只被调用两轮（ask 一轮 + 终答一轮）
    assert brain.rounds == 2


def test_multi_mode_ask_user_does_not_pause():
    # allow_ask_user=False（multi 子任务场景）：sentinel 被替换为继续指令，不产生 need_input
    from app.core.events import RunEventEmitter

    class AskThenFinalBrain:
        def __init__(self) -> None:
            self.usage: dict = {}
            self.rounds = 0

        def next_step(self, task: str, history: list[Step]) -> Step:
            self.rounds += 1
            if self.rounds == 1:
                return Step(
                    calls=[
                        {
                            "name": "ask_user",
                            "arguments": {"question": "要哪个文件？"},
                            "id": "c1",
                        }
                    ]
                )
            return Step(final="基于已有信息完成")

    brain = AskThenFinalBrain()
    registry = gmod.ToolRegistry()
    registry.register("ask_user", make_ask_user_tool(), description="x", parameters={"type": "object"})
    emitter = RunEventEmitter("t-multi", "t-multi")
    res = run_react(
        "任务",
        brain,
        registry,
        emitter=emitter,
        emit=lambda ev: None,
        allow_ask_user=False,
    )
    assert res.need_input is None
    assert "无法中途向用户确认" in (res.steps[0].observation or "")
    assert res.final == "基于已有信息完成"
    assert brain.rounds == 2


def test_ask_user_tool_requires_question():
    tool = make_ask_user_tool()
    out = tool(question="  ")
    assert "error" in out  # 空问题拒收——弹出去用户面前的话必须有内容
    out2 = tool(question="要哪个文件？", options=["a.csv", "b.xlsx"], need_file=True)
    assert out2["__ask_user__"] is True
    assert out2["questions"][0]["options"] == ["a.csv", "b.xlsx"]
    # 多问题：questions 列表一次带多个，前端 n/N 逐题收集
    out3 = tool(questions=[
        {"question": "文件格式？", "options": ["csv", "xlsx"]},
        {"question": "关键列是哪列？"},
    ])
    assert len(out3["questions"]) == 2
    assert out3["questions"][0]["options"] == ["csv", "xlsx"]


def test_resume_without_archive_fails_loudly(monkeypatch):
    # p5.4 铁律：无存档时 Command(resume) 会静默从头重跑——resume_with_answer 必须报错
    import pytest

    monkeypatch.setattr(gmod, "_take_live_checkpointer", lambda rid: None)
    monkeypatch.setattr(gmod.settings, "checkpointer_backend", "memory", raising=False)
    with pytest.raises(ValueError, match="存档已失效"):
        gmod.resume_with_answer(
            "t-no-archive",
            "回答",
            emitter=gmod.RunEventEmitter("t-no-archive", "t-no-archive"),
            emit=lambda ev: None,
        )


def test_seed_reaches_tool_calls_messages():
    """2.1.0 P1-1n hotfix 回归：tool_calls 协议下 seed 必须以 user 消息进入模型消息。

    生产实测：seed Step 无 action → _messages_for_tool_calls 跳过 → 模型收不到
    用户回答，在 ask_user 后直接给终答（"等你确认后就能直接开跑"）。"""
    from app.orchestration.brain import LlmBrain
    from app.orchestration.react import Step

    brain = LlmBrain.__new__(LlmBrain)  # 只测消息构建，不走 __init__
    messages = LlmBrain._messages_for_tool_calls(
        "任务",
        [
            Step(thought="需要确认", action="ask_user", action_input={"questions": []}, observation="已向用户发起补充输入请求"),
            Step(thought="", observation="用户已补充输入：选 A；已上传文件：sales.csv"),
        ],
    )
    user_msgs = [m for m in messages if m["role"] == "user"]
    assert any("选 A" in m["content"] and "sales.csv" in m["content"] for m in user_msgs)
    # ask_user 的占位观察仍走 role=tool（红线：工具观察不进 user 文本）
    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert any("已向用户发起补充输入请求" in m["content"] for m in tool_msgs)
