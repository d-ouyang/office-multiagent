"""p5.4：checkpointer 后端选择 + 持久化真续跑。

核心断言来自探针实测（langgraph 1.2.16）：
  · sqlite：换新实例后 resume，**已完成的节点不重跑**；
  · memory 新实例 / 无存档 thread：LangGraph 不报错而是**静默从头重跑**，
    所以 resume_task 必须先校验存档，把问题暴露在续跑之前。
"""
import pytest
from typing_extensions import TypedDict

from app.core.config import settings
from app.core.events import RunEventEmitter
from app.orchestration.checkpoints import get_checkpointer, reset_checkpointer_for_tests
from app.orchestration.graph import resume_task


@pytest.fixture(autouse=True)
def _reset_singleton():
    yield
    reset_checkpointer_for_tests()


class _S(TypedDict, total=False):
    status: str


def _build_graph(saver, counter, wallet):
    """step0（有副作用计数）→ quota（余额不足即 interrupt）→ END。"""
    from langgraph.graph import END, StateGraph
    from langgraph.types import interrupt

    def step0(state):
        counter["step0"] += 1
        return {"status": "step0"}

    def quota(state):
        counter["quota"] += 1
        if not wallet["ok"]:
            interrupt({"type": "quota_paused"})
        return {"status": "running"}

    g = StateGraph(_S)
    g.add_node("step0", step0)
    g.add_node("quota", quota)
    g.set_entry_point("step0")
    g.add_edge("step0", "quota")
    g.add_edge("quota", END)
    return g.compile(checkpointer=saver)


def test_memory_backend_returns_fresh_instance_each_time(monkeypatch):
    """缺省 memory：每次新建，严格保持 p5.4 之前的行为（不做隐式共享）。"""
    monkeypatch.setattr(settings, "checkpointer_backend", "memory")
    assert get_checkpointer() is not get_checkpointer()


def test_unknown_backend_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "checkpointer_backend", "postgres")
    with pytest.raises(ValueError, match="checkpointer_backend"):
        get_checkpointer()


def test_sqlite_backend_shares_one_instance(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "checkpointer_backend", "sqlite")
    monkeypatch.setattr(settings, "checkpoint_sqlite_path", str(tmp_path / "cp.sqlite"))
    assert get_checkpointer() is get_checkpointer()
    assert (tmp_path / "cp.sqlite").exists()


def test_sqlite_resume_does_not_replay_completed_nodes(tmp_path, monkeypatch):
    """跨实例（≈跨进程重启）恢复：从断点续跑，而不是从头重跑。"""
    monkeypatch.setattr(settings, "checkpointer_backend", "sqlite")
    monkeypatch.setattr(settings, "checkpoint_sqlite_path", str(tmp_path / "cp.sqlite"))
    counter = {"step0": 0, "quota": 0}
    wallet = {"ok": False}
    cfg = {"configurable": {"thread_id": "t-1"}}

    graph = _build_graph(get_checkpointer(), counter, wallet)
    first = graph.invoke({"status": "new"}, cfg)
    assert "__interrupt__" in first
    assert counter == {"step0": 1, "quota": 1}

    # 模拟进程重启：共享单例销毁，随后按同一 db 路径重建
    reset_checkpointer_for_tests()
    wallet["ok"] = True
    graph2 = _build_graph(get_checkpointer(), counter, wallet)
    out = resume_task(graph2, "t-1", RunEventEmitter("r", "t2"), lambda e: None)

    assert out["status"] == "running"
    assert counter["step0"] == 1  # 关键：已完成节点未重跑 → 不重复执行、不重复计费
    assert counter["quota"] == 2  # 挂起点按预期重试


def test_resume_without_saved_checkpoint_raises(tmp_path, monkeypatch):
    """无存档时必须报错，而不是被 LangGraph 静默从头重跑。"""
    monkeypatch.setattr(settings, "checkpointer_backend", "sqlite")
    monkeypatch.setattr(settings, "checkpoint_sqlite_path", str(tmp_path / "cp.sqlite"))
    counter = {"step0": 0, "quota": 0}
    graph = _build_graph(get_checkpointer(), counter, {"ok": True})

    with pytest.raises(ValueError, match="没有可续跑"):
        resume_task(graph, "no-such-thread", RunEventEmitter("r", "t"), lambda e: None)
    assert counter["step0"] == 0  # 确认没有发生任何重跑


def test_memory_new_instance_cannot_resume_is_caught(tmp_path, monkeypatch):
    """对照组：memory 存档随实例丢失，续跑会被我们的校验拦下（而非静默重跑）。"""
    monkeypatch.setattr(settings, "checkpointer_backend", "memory")
    counter = {"step0": 0, "quota": 0}
    wallet = {"ok": False}
    cfg = {"configurable": {"thread_id": "t-1"}}

    graph = _build_graph(get_checkpointer(), counter, wallet)
    assert "__interrupt__" in graph.invoke({"status": "new"}, cfg)

    wallet["ok"] = True
    fresh = _build_graph(get_checkpointer(), counter, wallet)  # 新实例 = 存档已丢
    with pytest.raises(ValueError, match="没有可续跑"):
        resume_task(fresh, "t-1", RunEventEmitter("r", "t2"), lambda e: None)
    assert counter["step0"] == 1  # 没有静默重跑已完成节点
