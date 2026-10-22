"""把结论写成 md 或 docx。不生成表格文件，也不画图。

文件放在当前用户上传目录的 _out/ 下。传入 clean_id 时，文末附上这份清洗结果的来源，
正文里的数字仍由调用方根据 analyze_table 的返回来写。
"""
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .tools_store import finish_output, new_output_id, output_file
from .tools_table import _load_clean

_FORMATS = {"md": ".md", "docx": ".docx"}
_MAX_CHARS = 80_000


def _safe_title(title: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', " ", title or "").strip()
    return (cleaned[:40] or "总结")


def _source_note(base: Path, clean_id: str) -> str:
    headers, rows, meta = _load_clean(base, clean_id)
    source = meta.get("source") or "未知文件"
    columns = "、".join(headers) if headers else "（无列）"
    return (
        f"数据来源\n"
        f"原文件：{source}\n"
        f"清洗编号：{clean_id}\n"
        f"列：{columns}\n"
        f"清洗后行数：{len(rows)}"
    )


def _markdown_body(title: str, content: str, note: str) -> str:
    body = content.strip()
    if not body.startswith("#"):
        body = f"# {title}\n\n{body}"
    if note:
        body = f"{body}\n\n---\n\n{note}\n"
    return body


def _write_docx(path: Path, title: str, content: str, note: str) -> None:
    from docx import Document

    doc = Document()
    if not content.strip().startswith("#"):
        doc.add_heading(title, level=1)
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("### "):
            doc.add_heading(stripped[4:].strip(), level=3)
        elif stripped.startswith("## "):
            doc.add_heading(stripped[3:].strip(), level=2)
        elif stripped.startswith("# "):
            doc.add_heading(stripped[2:].strip(), level=1)
        elif stripped.startswith(("- ", "* ")):
            doc.add_paragraph("• " + stripped[2:].strip())
        else:
            doc.add_paragraph(stripped)
    if note:
        doc.add_paragraph("")
        for line in note.splitlines():
            if line.strip():
                doc.add_paragraph(line.strip())
    doc.save(str(path))


def make_write_document_tool(
    *,
    base_dir: str,
    owner: str | None = None,
    engine: Any = None,
    user_id: int | None = None,
    task_id: str | None = None,
) -> Callable[..., Any]:
    del owner
    base = Path(base_dir).resolve()

    def write_document(
        title: str,
        content: str,
        format: str = "md",
        clean_id: str | None = None,
    ) -> dict[str, Any]:
        kind = (format or "md").strip().lower()
        if kind in {"markdown", "word"}:
            kind = "md" if kind == "markdown" else "docx"
        if kind not in _FORMATS:
            raise ValueError("write_document 只生成 md 或 docx。图请调用 render_chart。")
        body = (content or "").strip()
        if not body:
            raise ValueError("文档正文为空")
        if len(body) > _MAX_CHARS:
            raise ValueError(f"正文超过 {_MAX_CHARS} 字，请先缩短再生成")
        heading = _safe_title(title)
        note = ""
        if clean_id:
            note = _source_note(base, str(clean_id))
        doc_id = new_output_id("w")
        filename = doc_id + _FORMATS[kind]
        target = output_file(base, filename)
        if kind == "md":
            target.write_text(_markdown_body(heading, body, note), encoding="utf-8")
        else:
            _write_docx(target, heading, body, note)
        display = f"{heading}.{kind}"
        rel = f"_out/{filename}"
        recorded = finish_output(
            engine,
            target,
            asset_id=doc_id,
            user_id=user_id,
            task_id=task_id,
            kind=kind,
            name=display,
            rel_path=rel,
        )
        return {
            "doc_id": doc_id,
            "file_name": f"_out/{filename}",
            "display_name": display,
            "format": kind,
            "chars": len(body),
            "clean_id": clean_id or None,
            "recorded": recorded,
            "note": "文件已写在服务器上，请用返回的文件名预览。图要另调 render_chart。",
        }

    write_document.__name__ = "write_document"
    return write_document
