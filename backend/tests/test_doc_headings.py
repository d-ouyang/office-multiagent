"""v2.4.0-p5.0：目录索引（headings）测试（H-1 ~ H-6）。

为什么：9.3 万字文档问"第 20 章多少"，模型只能整段读 → 两轮 prefill 15 万 token → 73 秒。
目录索引给出"标题 + 字符偏移"，模型可直接定位精读。**无标题文档退回原分段读**，
行为与 p2.0 一致（这是本步的兼容底线）。
"""
import pytest

from app.orchestration.tools_doc import MAX_HEADINGS, extract_headings, make_read_document_tool


def _tool(tmp_path, text: str, max_chars: int = 50000):
    (tmp_path / "a.md").write_text(text, encoding="utf-8")
    return make_read_document_tool(base_dir=str(tmp_path), max_chars=max_chars)


#: Markdown 三级标题
MD = "\n".join([
    "# 总则",
    "正文A" * 100,
    "## 第一节",
    "正文B" * 100,
    "### 细则",
    "正文C" * 100,
])


def _cn_doc(n: int = 5) -> str:
    """每章一行标题 + 一行正文（真实文档的排版：标题独立成行）。"""
    parts: list[str] = []
    for i in range(1, n + 1):
        parts.append(f"第{i}章 测试内容")
        parts.append("正文" * 200)
    return "\n".join(parts)


def test_markdown_headings_levels():
    """H-1：Markdown 标题识别 + 层级正确。"""
    heads, truncated = extract_headings(MD)
    assert [h["title"] for h in heads] == ["总则", "第一节", "细则"]
    assert [h["level"] for h in heads] == [1, 2, 3]
    assert truncated is False


def test_cn_chapter_lines_recognized():
    """H-2：没有 # 号的「第N章」也能认（业务文档大多这样写）。"""
    heads, _ = extract_headings(_cn_doc())
    assert len(heads) == 5
    assert heads[0]["title"].startswith("第1章")
    offsets = [h["offset"] for h in heads]
    assert offsets == sorted(offsets)


def test_heading_offset_points_at_section(tmp_path):
    """H-3（最关键）：用目录里的 offset 精读，必须正好读到该章开头。"""
    tool = _tool(tmp_path, _cn_doc())
    heads = tool("a.md", headings_only=True)["headings"]
    target = heads[3]  # 第 4 章
    r = tool("a.md", offset=target["offset"], limit=50)
    assert r["content"].startswith("第4章")


def test_headings_only_returns_no_body(tmp_path):
    """H-4：只取目录时不返回正文（token 极省，适合先看结构）。"""
    tool = _tool(tmp_path, _cn_doc())
    r = tool("a.md", headings_only=True)
    assert r["content"] == ""
    assert r["returned_chars"] == 0
    assert r["has_more"] is True  # 正文还没读
    assert len(r["headings"]) == 5


def test_no_headings_falls_back_to_paging(tmp_path):
    """H-5（兼容底线）：无标题文档 headings 为空，分段读照旧可用。"""
    text = "abcdefg" * 3000  # 21000 字，无任何标题行
    tool = _tool(tmp_path, text, max_chars=5000)
    r = tool("a.md", limit=5000)
    assert r["headings"] == []
    assert r["has_more"] is True
    assert len(r["content"]) == 5000
    assert r["next_offset"] == 5000


def test_headings_capped_with_flag():
    """H-6：目录条数封顶，超出标 truncated（目录本身不能变噪音）。"""
    text = "\n".join(f"第{i}章" for i in range(1, 200))
    heads, truncated = extract_headings(text)
    assert len(heads) == MAX_HEADINGS
    assert truncated is True
