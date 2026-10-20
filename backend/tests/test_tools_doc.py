"""read_document 工具测试（p5.2）——路径护栏 / 格式白名单 / 截断，全部 fail-closed。"""
from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.orchestration.tools_doc import check_inside_base, make_read_document_tool


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


def test_unsupported_format_is_honest(doc_dir):
    tool = make_read_document_tool(base_dir=str(doc_dir))
    with pytest.raises(ValueError, match="不支持"):
        tool("photo.jpg")


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
