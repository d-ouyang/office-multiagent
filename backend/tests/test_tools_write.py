"""write_document：只写 md / docx，带来源脚注，并在事件流里留下可预览的产物。"""
import pytest

from app.core.events import EventType, RunEventEmitter
from app.orchestration.react import Step, run_react
from app.orchestration.tools import ToolRegistry
from app.orchestration.tools_doc import extract_document_text
from app.orchestration.tools_table import make_clean_table_tool
from app.orchestration.tools_write import make_write_document_tool


def test_write_md_and_reject_chart_format(tmp_path):
    tool = make_write_document_tool(base_dir=str(tmp_path))
    out = tool(title="周报", content="上海合计 12。", format="md")
    path = tmp_path / out["file_name"]
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# 周报")
    assert "上海合计 12。" in text
    assert out["display_name"] == "周报.md"
    with pytest.raises(ValueError, match="只生成 md 或 docx"):
        tool(title="图", content="不该写出", format="xlsx")
    assert not list((tmp_path / "_out").glob("*.xlsx"))


def test_write_docx_with_clean_source(tmp_path):
    (tmp_path / "订单.csv").write_text("地区,金额\n上海,12\n", encoding="utf-8")
    cleaned = make_clean_table_tool(base_dir=str(tmp_path))("订单.csv")
    tool = make_write_document_tool(base_dir=str(tmp_path))
    out = tool(
        title="销售总结",
        content="## 结论\n- 上海合计 12",
        format="docx",
        clean_id=cleaned["clean_id"],
    )
    text = extract_document_text(tmp_path / out["file_name"])
    assert "结论" in text
    assert "上海合计 12" in text
    assert "订单.csv" in text
    assert cleaned["clean_id"] in text
    assert "清洗后行数：1" in text


def test_missing_clean_id_does_not_write(tmp_path):
    tool = make_write_document_tool(base_dir=str(tmp_path))
    with pytest.raises(FileNotFoundError):
        tool(title="空", content="没有这份表", format="md", clean_id="c-" + "ab" * 8)
    assert not (tmp_path / "_out").exists() or not list((tmp_path / "_out").glob("*"))


def test_write_emits_artifact_event(tmp_path):
    tool = make_write_document_tool(base_dir=str(tmp_path))
    reg = ToolRegistry()
    reg.register("write_document", tool, "写文档")

    class Once:
        def __init__(self) -> None:
            self.n = 0

        def next_step(self, task, history):
            self.n += 1
            if self.n == 1:
                return Step(
                    action="write_document",
                    action_input={"title": "周报", "content": "合计 12。", "format": "md"},
                )
            return Step(final="已生成")

    events = []
    run_react("写总结", Once(), reg, emitter=RunEventEmitter("r", "t"), emit=events.append)
    artifacts = [ev for ev in events if ev.type == EventType.ARTIFACT]
    assert len(artifacts) == 1
    assert artifacts[0].data["name"] == "周报.md"
    assert str(artifacts[0].data["storage_url"]).startswith("_out/w-")
