"""write_document：只写 md / docx，带来源脚注，并在事件流里留下可预览的产物。"""
import pytest

from app.core.events import EventType, RunEventEmitter
from app.orchestration.react import Step, run_react
from app.orchestration.tools import ToolRegistry
from app.orchestration.tools_doc import extract_document_text
from app.orchestration.tools_table import make_clean_table_tool
from app.orchestration.tools_write import make_write_document_tool
from app.orchestration import tools_write


def test_write_pptx_and_pdf(tmp_path):
    tool = make_write_document_tool(base_dir=str(tmp_path))
    ppt = tool(title="销售汇报", content="## 结论\n- 上海合计 12", format="pptx")
    text = extract_document_text(tmp_path / ppt["file_name"])
    assert "销售汇报" in text
    assert "上海合计 12" in text
    pdf = tool(title="销售汇报", content="上海合计 12。", format="pdf")
    raw = (tmp_path / pdf["file_name"]).read_bytes()
    assert raw.startswith(b"%PDF")


def test_write_md_and_reject_chart_format(tmp_path):
    tool = make_write_document_tool(base_dir=str(tmp_path))
    out = tool(title="周报", content="上海合计 12。", format="md")
    path = tmp_path / out["file_name"]
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# 周报")
    assert "上海合计 12。" in text
    assert out["display_name"] == "周报.md"
    with pytest.raises(ValueError, match="只生成 md、docx、pdf 或 pptx"):
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


def _patch_font_cache(monkeypatch):
    """reportlab 字体注册是进程级缓存；全量跑时前面的 PDF 用例已注册 OfficeCJK，
    不清缓存则 _cjk_font 直接命中早退，走不到失败分支。"""
    from reportlab.pdfbase import pdfmetrics

    monkeypatch.setattr(pdfmetrics, "getRegisteredFontNames", lambda: [])


def test_pdf_cjk_font_failure_is_loud_and_actionable(monkeypatch):
    """p6.34：一个字体都注册不了时必须抛带指引的错误，且报错指向 TrueType。

    背景：Noto CJK/思源黑体是 CFF 轮廓，reportlab 注册必败；旧版静默 continue
    让「装了字体仍报没有字体」。这里把候选/目录全换掉，走确定性失败路径。
    """
    _patch_font_cache(monkeypatch)
    monkeypatch.setenv("PDF_FONT", "/nonexistent/font.ttf")
    monkeypatch.setattr(tools_write, "_CJK_FONT_CANDIDATES", ())
    monkeypatch.setattr(tools_write, "_CJK_FONT_DIRS", ())
    with pytest.raises(ValueError, match="TrueType"):
        tools_write._cjk_font()


def test_pdf_cjk_font_unreadable_font_is_skipped_with_log(monkeypatch, caplog, tmp_path):
    """p6.34：存在但注册失败的字体必须留 WARNING 日志，不许静默 continue（旧版坑）。"""
    import logging

    _patch_font_cache(monkeypatch)
    fake = tmp_path / "fake.ttf"
    fake.write_bytes(b"not a font")
    monkeypatch.setenv("PDF_FONT", str(fake))
    monkeypatch.setattr(tools_write, "_CJK_FONT_CANDIDATES", ())
    monkeypatch.setattr(tools_write, "_CJK_FONT_DIRS", ())
    with caplog.at_level(logging.WARNING, logger="app.orchestration.tools_write"):
        with pytest.raises(ValueError, match="TrueType"):
            tools_write._cjk_font()
    assert "fake.ttf" in caplog.text


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
