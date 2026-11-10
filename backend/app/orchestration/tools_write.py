"""把结论写成 md、docx、pdf 或 pptx。不生成表格文件，也不画图。

文件放在当前用户上传目录的 _out/ 下。传入 clean_id 时，文末附上这份清洗结果的来源，
正文里的数字仍由调用方根据 analyze_table 的返回来写。
"""
from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .tools_store import finish_output, new_output_id, output_file
from .tools_table import _load_clean

logger = logging.getLogger(__name__)

_FORMATS = {"md": ".md", "docx": ".docx", "pdf": ".pdf", "pptx": ".pptx"}
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


def _blocks(content: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("### "):
            rows.append(("h3", stripped[4:].strip()))
        elif stripped.startswith("## "):
            rows.append(("h2", stripped[3:].strip()))
        elif stripped.startswith("# "):
            rows.append(("h1", stripped[2:].strip()))
        elif stripped.startswith(("- ", "* ")):
            rows.append(("li", stripped[2:].strip()))
        else:
            rows.append(("p", stripped))
    return rows


def _picture_file(image: Path | None) -> Path | None:
    if image is None:
        return None
    png = image if image.suffix.lower() == ".png" else image.with_suffix(".png")
    return png if png.is_file() else None


# reportlab 的 TTFont 只认 TrueType（glyf）轮廓。思源黑体/Noto CJK 是 CFF
# （PostScript）轮廓，注册必败（"postscript outlines are not supported"）。
# 候选只列 TrueType 轮廓的中文字体，按优先级排列。
_CJK_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
)
_CJK_FONT_DIRS = (
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "/System/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
    "/Library/Fonts",
)
# reportlab 的 TTFont 只认 TrueType（glyf）轮廓。思源黑体/Noto CJK 是 CFF
# （PostScript）轮廓，注册必败（"postscript outlines are not supported"）。
# 候选只列 TrueType 轮廓的中文字体，按优先级排列。
_CJK_FONT_NAMES = (
    "wqy-microhei.ttc",
    "wqy-zenhei.ttc",
    "DroidSansFallbackFull.ttf",
    "DroidSansFallback.ttf",
    "uming.ttc",
    "ukai.ttc",
    "simhei.ttf",
    "simsun.ttc",
    "msyh.ttc",
    "msyh.ttf",
    "Arial Unicode.ttf",
)


def _cjk_font() -> str:
    """注册一份中文字体供 PDF 嵌入。找不到就如实失败，不生成缺字的 PDF。

    坑（2026-10-24 实测）：fonts-noto-cjk 的 .ttc 是 CFF 轮廓，reportlab 注册直接抛
    "postscript outlines are not supported"；旧版静默 continue，表现为
    「装了思源黑体仍提示没有可用字体」。修法：Dockerfile 加装 TrueType 轮廓的
    文泉驿微米黑（fonts-wqy-microhei），注册失败写 WARNING 日志，不再静默。
    """
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if "OfficeCJK" in pdfmetrics.getRegisteredFontNames():
        return "OfficeCJK"

    candidates = [raw for raw in (os.environ.get("PDF_FONT", ""),) if raw]
    candidates += list(_CJK_FONT_CANDIDATES)
    # 兜底：常见字体目录按文件名扫一遍（不同发行版/宿主机的字体路径会漂）
    seen = set(candidates)
    for font_dir in _CJK_FONT_DIRS:
        root = Path(font_dir)
        if not root.is_dir():
            continue
        for name in _CJK_FONT_NAMES:
            for hit in root.rglob(name):
                text = str(hit)
                if text not in seen:
                    seen.add(text)
                    candidates.append(text)

    failures: list[str] = []
    for raw in candidates:
        path = Path(raw)
        if not path.is_file():
            continue
        try:
            if path.suffix.lower() == ".ttc":
                pdfmetrics.registerFont(TTFont("OfficeCJK", str(path), subfontIndex=0))
            else:
                pdfmetrics.registerFont(TTFont("OfficeCJK", str(path)))
            return "OfficeCJK"
        except Exception as exc:  # noqa: BLE001 - 单个字体注册失败换下一个，但必须留痕
            failures.append(f"{path.name}: {exc}")
            continue
    if failures:
        logger.warning(
            "中文字体注册全部失败（多为 CFF 轮廓，reportlab 不支持）| %s",
            "; ".join(failures[:5]),
        )
    raise ValueError(
        "没有可用的中文字体，PDF 未生成。PDF 内嵌字体必须是 TrueType 轮廓："
        "容器请安装 fonts-wqy-microhei（文泉驿微米黑），或设置环境变量 PDF_FONT "
        "指向 .ttf/.ttc。注意：思源黑体/Noto CJK 是 CFF 轮廓，reportlab 不支持。"
    )


def _write_pdf(path: Path, title: str, content: str, note: str, image: Path | None) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Image as PdfImage
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    font = _cjk_font()
    styles = {
        "h1": ParagraphStyle("h1", fontName=font, fontSize=18, leading=24, spaceAfter=8),
        "h2": ParagraphStyle("h2", fontName=font, fontSize=14, leading=20, spaceBefore=8, spaceAfter=4),
        "h3": ParagraphStyle("h3", fontName=font, fontSize=12, leading=18, spaceBefore=6, spaceAfter=4),
        "p": ParagraphStyle("p", fontName=font, fontSize=11, leading=16, spaceAfter=4),
        "li": ParagraphStyle("li", fontName=font, fontSize=11, leading=16, leftIndent=12, spaceAfter=2),
    }
    # 2.1.0：标题去重——模型常把标题同时写进 title 参数与正文首行 H1，
    # 无条件加 title 会渲染两个相同标题（生产实测）。首行 H1 与 title 同名则剥掉首行。
    body_lines = content.splitlines()
    first = next((ln for ln in body_lines if ln.strip()), "")
    if first.strip().startswith("# ") and first.strip()[2:].strip() == title.strip():
        idx = body_lines.index(first)
        body_lines = body_lines[idx + 1:]
        content = "\n".join(body_lines)
    story = [Paragraph(_xml(title), styles["h1"])]
    for kind, text in _blocks(content):
        shown = "• " + text if kind == "li" else text
        story.append(Paragraph(_xml(shown), styles.get(kind, styles["p"])))
    picture = _picture_file(image)
    if picture is not None:
        story.append(Spacer(1, 4 * mm))
        story.append(PdfImage(str(picture), width=150 * mm, height=80 * mm, kind="proportional"))
    elif image is not None:
        story.append(Paragraph(_xml(f"（图表 {image.name} 无法嵌入 PDF：缺少 png）"), styles["p"]))
    if note:
        story.append(Spacer(1, 6 * mm))
        for line in note.splitlines():
            if line.strip():
                story.append(Paragraph(_xml(line.strip()), styles["p"]))
    SimpleDocTemplate(str(path), pagesize=A4, title=title).build(story)


def _xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _write_pptx(path: Path, title: str, content: str, note: str, image: Path | None) -> None:
    from pptx import Presentation
    from pptx.util import Inches, Pt

    pres = Presentation()
    pres.slide_width = Inches(13.333)
    pres.slide_height = Inches(7.5)
    opening = pres.slides.add_slide(pres.slide_layouts[0])
    opening.shapes.title.text = title
    if len(opening.placeholders) > 1:
        opening.placeholders[1].text = "由办公助手生成"
    body_lines = [text for _, text in _blocks(content)]
    picture = _picture_file(image)
    chunk: list[str] = []
    for line in body_lines:
        chunk.append(line)
        if len(chunk) == 6:
            _add_bullet_slide(pres, title, chunk)
            chunk = []
    if chunk or not body_lines:
        _add_bullet_slide(pres, title, chunk or ["（无正文）"])
    if picture is not None:
        slide = pres.slides.add_slide(pres.slide_layouts[5])
        slide.shapes.title.text = "图表"
        slide.shapes.add_picture(str(picture), Inches(1.2), Inches(1.6), width=Inches(10))
    if note:
        _add_bullet_slide(pres, "数据来源", [line.strip() for line in note.splitlines() if line.strip()])
    for slide in pres.slides:
        for shape in slide.shapes:
            if not getattr(shape, "has_text_frame", False):
                continue
            for paragraph in shape.text_frame.paragraphs:
                for run in paragraph.runs:
                    run.font.name = "PingFang SC"
                    if run.font.size is None:
                        run.font.size = Pt(18)
    pres.save(str(path))


def _add_bullet_slide(pres: Any, title: str, lines: list[str]) -> None:
    from pptx.util import Pt

    slide = pres.slides.add_slide(pres.slide_layouts[1])
    slide.shapes.title.text = title[:40]
    frame = slide.placeholders[1].text_frame
    frame.clear()
    for index, line in enumerate(lines):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = line
        paragraph.level = 0
        paragraph.font.size = Pt(20)


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
        aliases = {"markdown": "md", "word": "docx", "powerpoint": "pptx", "ppt": "pptx"}
        kind = aliases.get(kind, kind)
        if kind not in _FORMATS:
            raise ValueError("write_document 只生成 md、docx、pdf 或 pptx。图请调用 render_chart，流程请调用 render_flow。")
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
        image_path = base / image_rel if image_rel else None
        if kind == "md":
            target.write_text(_markdown_body(heading, body, note, image_rel), encoding="utf-8")
        elif kind == "docx":
            _write_docx(target, heading, body, note, image_path)
        elif kind == "pdf":
            _write_pdf(target, heading, body, note, image_path)
        else:
            _write_pptx(target, heading, body, note, image_path)
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
