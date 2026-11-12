"""Policy / StateSnapshot / EvalCase 三契约测试（v2.2.0-p1.3 / Phase A4）。

A4 判据：契约可独立单测（零数据库依赖）、字段语义自洽、序列化形态稳定
（Phase E1 的 golden set 文件格式即 to_dict 的 JSON）。
"""
from app.core.contracts import EvalCase, PolicyDecision, StateSnapshot, Verdict


# --------------------------------------------------------------------------- #
# Policy
# --------------------------------------------------------------------------- #


def test_policy_decision_allow_shape_is_minimal():
    d = PolicyDecision(allow=True)
    assert d.reason == "" and d.budget_cap is None and not d.hitl_required
    assert d.degrade_chain == ()


def test_policy_decision_quota_pause_shape():
    """现状映射：quota 暂停 = allow=False + reason + 剩余额度。"""
    d = PolicyDecision(allow=False, reason="quota", budget_cap=120)
    assert not d.allow and d.budget_cap == 120
    assert d.degrade_chain == ()


def test_policy_decision_degrade_chain_is_immutable_tuple():
    """降级链用 tuple：契约对象不可被调用方原地改（frozen dataclass 同理）。"""
    d = PolicyDecision(allow=False, reason="model_unavailable", degrade_chain=("ollama", "deepseek"))
    assert d.degrade_chain == ("ollama", "deepseek")


def test_policy_engine_protocol_is_satisfiable_by_plain_class():
    """任何 decide(...) 签名匹配的类都满足契约（runtime_checkable duck typing）。"""

    class Wallet:
        def decide(self, *, user_id: int, action: str, estimated_cost: int | None = None):
            return PolicyDecision(allow=estimated_cost is None or estimated_cost < 100)

    assert isinstance(Wallet(), __import__("app.core.contracts", fromlist=["PolicyEngine"]).PolicyEngine)


# --------------------------------------------------------------------------- #
# StateSnapshot
# --------------------------------------------------------------------------- #


def test_state_snapshot_defaults_for_pre_c2_world():
    """C2 落地前：lease_owner=None、state 空 dict——即「无锁快照」仍合法。"""
    s = StateSnapshot(run_id="r1", version=5)
    assert s.lease_owner is None and s.state == {} and s.checkpoint_ts == 0


def test_state_snapshot_version_drives_resume_scope():
    """恢复语义：version=事件流 seq——≤version 的步骤不重算（C3 判据基础）。"""
    s = StateSnapshot(run_id="r1", version=8, state={"last_node": "react"}, lease_owner="worker-1")
    assert s.version == 8 and s.lease_owner == "worker-1"


def test_state_snapshot_is_frozen():
    s = StateSnapshot(run_id="r1", version=1)
    try:
        s.version = 2  # type: ignore[misc]
        raise AssertionError("frozen dataclass 应拒绝原地修改")
    except AttributeError:
        pass


# --------------------------------------------------------------------------- #
# EvalCase
# --------------------------------------------------------------------------- #


def test_eval_case_undecided_golden_entry():
    c = EvalCase(case_id="g-001", input="上月上海销售额多少", expected="32,926")
    assert c.verdict is None and c.to_dict()["verdict"] is None


def test_eval_case_badcase_from_dislike_flow():
    """点踩回流：input=用户原话，verdict 直接 fail（E1 回流管道入口形态）。"""
    c = EvalCase(
        case_id="fb-12", input="帮我查下预算", trace_ref="task-42",
        verdict=Verdict(passed=False, notes="数据或数字有误"),
    )
    d = c.to_dict()
    assert d["verdict"] == {"passed": False, "score": None, "notes": "数据或数字有误"}


def test_eval_case_rag_shape_with_score():
    c = EvalCase(
        case_id="rag-7", input="年假几天", retrieved="《考勤制度》第3条", trace_ref="run-abc",
        verdict=Verdict(passed=True, score=0.93, notes="grounded"),
    )
    assert c.verdict and c.verdict.score == 0.93
    assert c.to_dict()["retrieved"] == "《考勤制度》第3条"
