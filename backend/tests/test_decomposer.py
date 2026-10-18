"""子任务 DAG 拆分测试（p3.2，§四.2 第三步）。确定性规则，固定用例精确断言。"""
import pytest

from app.core.decomposer import DAG, Subtask, decompose
from app.core.planner import plan


def test_single_intent_no_deps():
    dag = decompose(plan("帮我查一下公司制度"))
    assert len(dag.subtasks) == 1
    assert dag.subtasks[0].depends_on == []


def test_multi_intent_dependency_edges_and_topo():
    dag = decompose(plan("先清洗数据，然后分析，再生成报表，同时导出 excel 和 pdf"))
    byid = dag.by_id()
    assert {"cleaning", "analysis", "report"} <= set(byid)
    assert byid["analysis"].depends_on == ["cleaning"]
    assert byid["report"].depends_on == ["analysis"]
    topo = [s.id for s in dag.topo_order()]
    assert topo.index("cleaning") < topo.index("analysis") < topo.index("report")


def test_dependency_ignored_when_prereq_absent():
    # 只有 analysis + report（无 cleaning）→ analysis 不依赖不在场的 cleaning
    dag = decompose(plan("分析一下销售，然后出报表"))
    byid = dag.by_id()
    assert "cleaning" not in byid
    assert byid["analysis"].depends_on == []
    assert byid["report"].depends_on == ["analysis"]


def test_independent_intents_have_no_deps():
    dag = decompose(plan("查一下知识库，同时把这张截图的表格还原成数据"))
    byid = dag.by_id()
    assert byid["rag"].depends_on == []
    assert byid["image_restore"].depends_on == []


def test_cycle_detection_fail_fast():
    dag = DAG(
        subtasks=[
            Subtask(id="a", agent_type="x", intent="a", depends_on=["b"]),
            Subtask(id="b", agent_type="y", intent="b", depends_on=["a"]),
        ]
    )
    with pytest.raises(ValueError, match="环"):
        dag.topo_order()


def test_to_dict_shape():
    dag = decompose(plan("先清洗，再分析，再出报表"))
    d = dag.to_dict()
    assert set(d) == {"subtasks", "topo_order"}
    assert all("depends_on" in s for s in d["subtasks"])
