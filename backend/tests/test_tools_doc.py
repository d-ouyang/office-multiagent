"""read_document 工具测试（p5.2）——路径护栏 / 格式白名单 / 截断，全部 fail-closed。"""
from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.orchestration.tools_doc import check_inside_base, make_read_document_tool, normalize_doc_name


@pytest.fixture
def doc_dir(tmp_path: Path) -> Path:
    base = tmp_path / "upload"
    base.mkdir()
    (base / "leave.md").write_text("# 年假制度\n入职满一年 5 天。", encoding="utf-8")
    (base / "empty.md").write_text("", encoding="utf-8")
    (base / "note.txt").write_text("纯文本内容", encoding="utf-8")
    (base / "photo.jpg").write_bytes(b"\xff\xd8fake")
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with (base / "blank.pdf").open("wb") as f:
        writer.write(f)
    return base


def test_read_md(doc_dir):
    tool = make_read_document_tool(base_dir=str(doc_dir))
    out = tool("leave.md")
    assert out["total_chars"] > 0 and "年假" in out["content"]
    assert out["truncated"] is False


def test_read_txt(doc_dir):
    tool = make_read_document_tool(base_dir=str(doc_dir))
    assert tool("note.txt")["content"] == "纯文本内容"


def test_read_pdf_returns_empty_page_text_or_ok(doc_dir):
    # pypdf 对空白页 extract_text 返回空串 → 工具如实报"内容为空"（不编造）
    tool = make_read_document_tool(base_dir=str(doc_dir))
    with pytest.raises(ValueError, match="内容为空"):
        tool("blank.pdf")


def test_read_csv_previews_header_and_limits_rows(doc_dir):
    lines = ["姓名,城市"] + [f"人{i},上海" for i in range(1, 26)]
    (doc_dir / "orders.csv").write_text("\n".join(lines), encoding="utf-8")
    tool = make_read_document_tool(base_dir=str(doc_dir))
    out = tool("orders.csv")
    assert "列：姓名、城市" in out["content"]
    assert "共 25 行，这里只给出前 20 行" in out["content"]
    assert "人20" in out["content"]
    assert "人21" not in out["content"]


def test_read_json_and_invalid_json(doc_dir):
    (doc_dir / "ok.json").write_text('{"名称": "备案"}', encoding="utf-8")
    (doc_dir / "bad.json").write_text("{不是", encoding="utf-8")
    tool = make_read_document_tool(base_dir=str(doc_dir))
    assert "备案" in tool("ok.json")["content"]
    bad = tool("bad.json")["content"]
    assert bad.startswith("不是合法 JSON")
    assert "{不是" in bad


def test_read_docx_paragraph_and_table(doc_dir):
    from docx import Document

    doc = Document()
    doc.add_paragraph("备案说明")
    table = doc.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "项目"
    table.rows[0].cells[1].text = "材料"
    table.rows[1].cells[0].text = "网站"
    table.rows[1].cells[1].text = "执照"
    doc.save(doc_dir / "说明.docx")
    tool = make_read_document_tool(base_dir=str(doc_dir))
    out = tool("说明.docx")["content"]
    assert "备案说明" in out
    assert "列：项目、材料" in out
    assert "网站 | 执照" in out


def test_read_xlsx_sheet_preview(doc_dir):
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "订单"
    sheet.append(["地区", "金额"])
    sheet.append(["上海", 12])
    book.save(doc_dir / "订单.xlsx")
    tool = make_read_document_tool(base_dir=str(doc_dir))
    out = tool("订单.xlsx")["content"]
    assert "工作表 订单" in out
    assert "列：地区、金额" in out
    assert "上海 | 12" in out
    assert "共 1 行" in out


def test_unsupported_format_is_honest(doc_dir):
    # p6.24 起 .jpg/.png/.webp 已进白名单（扫描件/图片走 OCR）——不支持格式改用 .exe
    (doc_dir / "virus.exe").write_bytes(b"MZ")
    tool = make_read_document_tool(base_dir=str(doc_dir))
    with pytest.raises(ValueError, match="不支持"):
        tool("virus.exe")


def test_missing_file_is_honest(doc_dir):
    tool = make_read_document_tool(base_dir=str(doc_dir))
    with pytest.raises(FileNotFoundError):
        tool("nope.md")


def test_empty_file_is_honest(doc_dir):
    tool = make_read_document_tool(base_dir=str(doc_dir))
    with pytest.raises(ValueError, match="内容为空"):
        tool("empty.md")


def test_truncates_and_marks(doc_dir):
    big = doc_dir / "big.md"
    big.write_text("字" * 100, encoding="utf-8")
    tool = make_read_document_tool(base_dir=str(doc_dir), max_chars=10)
    out = tool("big.md")
    assert len(out["content"]) == 10 and out["truncated"] is True


# ---------- 路径护栏（反向验证：越界必须拒） ----------
def test_path_traversal_rejected(doc_dir, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("机密", encoding="utf-8")
    tool = make_read_document_tool(base_dir=str(doc_dir))
    with pytest.raises(ValueError, match="非法路径"):
        tool("../secret.txt")


def test_absolute_path_rejected(doc_dir):
    tool = make_read_document_tool(base_dir=str(doc_dir))
    with pytest.raises(ValueError, match="非法路径"):
        tool("/etc/passwd")


def test_check_inside_base_allows_nested(doc_dir):
    (doc_dir / "sub").mkdir()
    p = check_inside_base(doc_dir, "sub/leave.md")
    assert p.name == "leave.md"


def test_owner_dir_accepts_basename_and_prefixed_name(doc_dir):
    """工具根目录已是用户目录时，文件名和「用户名/文件名」都能读到同一份文件。"""
    user = doc_dir / "dev"
    user.mkdir()
    (user / "指南.md").write_text("备案要点", encoding="utf-8")
    tool = make_read_document_tool(base_dir=str(user), owner="dev")
    assert tool("指南.md")["content"] == "备案要点"
    assert tool("dev/指南.md")["content"] == "备案要点"
    with pytest.raises(ValueError, match="非法路径"):
        tool("../leave.md")


def test_normalize_strips_only_owner_prefix():
    assert normalize_doc_name("dev/指南.pdf", "dev") == "指南.pdf"
    assert normalize_doc_name("指南.pdf", "dev") == "指南.pdf"
    assert normalize_doc_name("dev/指南.pdf", None) == "dev/指南.pdf"
    assert normalize_doc_name("/etc/passwd", "dev") == "/etc/passwd"


def test_registry_scopes_read_to_username(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.orchestration.agents import build_default_registry

    base = tmp_path / "upload"
    (base / "dev").mkdir(parents=True)
    (base / "other").mkdir()
    (base / "dev" / "指南.md").write_text("本人的文件", encoding="utf-8")
    (base / "other" / "指南.md").write_text("别人的文件", encoding="utf-8")
    monkeypatch.setattr(settings, "documents_dir", str(base))
    reg = build_default_registry(None, username="dev")
    own = reg.call("read_document", file_name="指南.md", max_retries=0)
    assert own.ok and own.output["content"] == "本人的文件"
    prefixed = reg.call("read_document", file_name="dev/指南.md", max_retries=0)
    assert prefixed.ok and prefixed.output["content"] == "本人的文件"
    escaped = reg.call("read_document", file_name="../other/指南.md", max_retries=0)
    assert escaped.ok is False
