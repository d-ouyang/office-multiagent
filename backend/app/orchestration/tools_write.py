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


def _markdown_body(title: str, content: str, note: str, image_rel: str | None = None) -> str:
    body = content.strip()
    if not body.startswith("#"):
        body = f"# {title}\n\n{body}"
    if image_rel:
        name = image_rel.rsplit("/", 1)[-1]
        body = f"{body}\n\n![{name}]({name})"
    if note:
        body = f"{body}\n\n---\n\n{note}\n"
    return body


def _resolve_image(base: Path, raw: str) -> str:
    """校验 image_file：必须是本用户 _out/ 下真实存在的 svg/png（render_chart 产物）。"""
    from .tools_store import output_file

    name = str(raw or "").replace("\\", "/").strip().lstrip("/")
    if name.startswith("_out/"):
        name = name[len("_out/"):]
    if not re.match(r"^g-[0-9a-f]{16}\.(svg|png)$", name):
        raise ValueError(
            f"image_file 只接受 render_chart 返回的 png_file/svg（_out/g-*.png|svg），收到：{raw}"
        )
    target = output_file(base, name)
    if not target.is_file():
        raise ValueError(f"图片不存在：{name}。请先调用 render_chart 生成图表。")
    return f"_out/{name}"


def _write_docx(path: Path, title: str, content: str, note: str, image: Path | None = None) -> None:
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
    if image is not None:
        # svg 嵌不进 docx——render_chart 现在总是同时产出同名 png，优先取它
        from docx.shared import Inches

        png = image if image.suffix.lower() == ".png" else image.with_suffix(".png")
        if png.is_file():
            doc.add_picture(str(png), width=Inches(6.0))
            doc.add_paragraph("")
        else:
            doc.add_paragraph(f"（图表 {image.name} 无法嵌入 docx：只有 svg 版本，请改用 md 格式）")
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
        image_file: str | None = None,
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
        # p6.30：嵌入图表（render_chart 产物）。md 用相对引用；docx 用 add_picture 嵌 png。
        image_rel = _resolve_image(base, image_file) if image_file else None
        doc_id = new_output_id("w")
        filename = doc_id + _FORMATS[kind]
        target = output_file(base, filename)
        if kind == "md":
            target.write_text(_markdown_body(heading, body, note, image_rel), encoding="utf-8")
        else:
            _write_docx(target, heading, body, note, base / image_rel if image_rel else None)
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
            "image_file": image_rel or None,
            "recorded": recorded,
            "note": (
                "文件已写在服务器上，请用返回的文件名预览。"
                + ("已嵌入图表。" if image_rel else "需要嵌图时先调 render_chart，再把它的 png_file 传给 image_file。")
            ),
        }

    write_document.__name__ = "write_document"
    return write_document
