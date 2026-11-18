"""v2.4.0-p3.0：文件名不准时的自我纠正提示（C-1 ~ C-3）。

背景：文件在目录里，模型却回"没找到，请上传"。除路由错（p1.3 已修），另一类变体是
文件名差一两个字符。给出相近候选，让模型自己纠正，而不是把信息缺失甩回给用户。
"""
import pytest

from app.orchestration.tools_doc import make_read_document_tool


def _tool(tmp_path):
    return make_read_document_tool(base_dir=str(tmp_path))


def test_suggests_similar_filename(tmp_path):
    """C-1：名字差一个字符 → 错误里列出相近文件，并明确"不要向用户索要"。"""
    (tmp_path / "smoke-long.md").write_text("x" * 10, encoding="utf-8")
    with pytest.raises(FileNotFoundError) as ei:
        _tool(tmp_path)("smoke_long.md")
    msg = str(ei.value)
    assert "相近的文件" in msg
    assert "smoke-long.md" in msg
    assert "不要向用户索要" in msg


def test_no_hint_when_nothing_similar(tmp_path):
    """C-2：确实没有相近文件时不乱猜——只说没找到。"""
    (tmp_path / "alpha.md").write_text("x", encoding="utf-8")
    with pytest.raises(FileNotFoundError) as ei:
        _tool(tmp_path)("完全无关的文件名zzz.pptx")
    assert "相近的文件" not in str(ei.value)


def test_path_traversal_still_blocked(tmp_path):
    """C-3：提示机制不能绕过路径护栏——越界仍是 ValueError，不泄漏目录结构。"""
    with pytest.raises(ValueError):
        _tool(tmp_path)("../../etc/passwd")
