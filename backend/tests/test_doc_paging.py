"""v2.4.0-p2.0：read_document 分段读取测试（B-1 ~ B-5）。

背景：整读超过单步上限就截尾，文档末尾章节模型永远看不到——真跑事故（2026-11-17）
2.4 万字文件的第 10 章被切掉，模型只能"按规律推断"。分段后可按 next_offset 续读。
"""
import pytest

from app.core.config import settings
from app.orchestration.tools_doc import make_read_document_tool


def _tool(tmp_path, text: str, max_chars: int = 50000):
    (tmp_path / "a.md").write_text(text, encoding="utf-8")
    return make_read_document_tool(base_dir=str(tmp_path), max_chars=max_chars)


def test_default_reads_whole_small_doc(tmp_path):
    """B-1：不传 offset/limit 时行为不变（整读），兼容所有现有调用。"""
    # 末尾不留空白：extract_document_text 对 .md 会 strip()，用 strip 后的文本做期望
    text = "\n".join(["第一段内容"] * 100)
    r = _tool(tmp_path, text)("a.md")
    assert r["content"] == text
    assert r["has_more"] is False
    assert r["offset"] == 0
    assert r["returned_chars"] == len(text)
    assert r["truncated"] is False


def test_paged_read_concatenates(tmp_path):
    """B-2：两段拼起来等于原文前 10000 字（分段不丢字、不重叠）。"""
    text = "".join(f"{i:04d}\n" for i in range(3000))  # 约 15000 字
    t = _tool(tmp_path, text)
    p1 = t("a.md", offset=0, limit=5000)
    assert p1["next_offset"] == 5000
    p2 = t("a.md", offset=p1["next_offset"], limit=5000)
    assert p1["content"] + p2["content"] == text[:10000]


def test_has_more_and_next_offset(tmp_path):
    """B-3：has_more / next_offset 如实反映剩余量，末段置 False。"""
    t = _tool(tmp_path, "x" * 50000)
    r = t("a.md", limit=5000)
    assert r["has_more"] is True and r["next_offset"] == 5000
    last = t("a.md", offset=45000, limit=10000)
    assert last["has_more"] is False and last["next_offset"] is None
    assert last["returned_chars"] == 5000


def test_offset_beyond_end_raises(tmp_path):
    """B-4：越界 offset 明确报错，不返回空串让模型猜。"""
    t = _tool(tmp_path, "abc")
    with pytest.raises(ValueError, match="超出文档长度"):
        t("a.md", offset=10)


def test_limit_capped_by_max_chars(tmp_path):
    """B-5：单次不会因为模型传大 limit 而突破产品上限。"""
    t = _tool(tmp_path, "y" * 20000, max_chars=4000)
    r = t("a.md", limit=999999)
    assert r["returned_chars"] == 4000
    assert r["has_more"] is True


def test_long_doc_last_chapter_reachable(tmp_path):
    """B-6（真跑回归）：上限压到 8000 时，靠分页仍能读到第 10 章。

    这正是 2026-11-17 那次"第 10 章被截断"的场景——以前无论怎么读都到不了末尾。
    """
    parts = []
    for i in range(1, 11):
        parts.append(f"第{i}章")
        parts.append("正文内容" * 400)
        parts.append(f"要点：上限 {i * 1000}")
    text = "\n".join(parts)
    t = _tool(tmp_path, text, max_chars=8000)

    first = t("a.md")
    assert first["has_more"] is True
    seen, cursor, pages = first["content"], first["next_offset"], 1
    while cursor is not None:
        part = t("a.md", offset=cursor)
        seen += part["content"]
        cursor = part["next_offset"]
        pages += 1

    assert pages > 1
    assert "要点：上限 10000" in seen  # 第 10 章终于可见
    assert len(seen) == len(text)


def test_task_budget_covers_multiple_doc_reads():
    """配置自洽护栏（v2.4.0-p2.1）：任务上限必须容得下"读一次 + 再读一段"。

    2026-11-17 真跑死锁：单步上限 50000 与任务上限 50000 相等——读一份 5 万字文档，
    第一次调用就把任务预算打满，直接 paused_budget（用户看到"已达单任务上限"）。
    这条断言把"两个数必须拉开一倍以上"钉死，避免以后再单独调其中一个。
    """
    assert settings.task_token_hard_limit >= settings.doc_read_max_chars * 2


def test_task_budget_covers_multiple_doc_reads():
    """配置自洽护栏（v2.4.0-p2.1）：任务上限必须容得下"读一次 + 再读一段"。

    2026-11-17 真跑死锁：单步上限 50000 与任务上限 50000 相等——读一份 5 万字文档，
    第一次调用就把任务预算打满，直接 paused_budget（用户看到"已达单任务上限"）。
    这条断言把"两个数必须拉开一倍以上"钉死，避免以后再单独调其中一个。
    """
    assert settings.task_token_hard_limit >= settings.doc_read_max_chars * 2
