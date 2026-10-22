"""read_document 工具（p5.2 / p6.14）——读取文档目录内的文本。

硬护栏（fail-closed）：
  · 路径穿越防护：解析后的真实路径必须仍在文档目录内（`..`、绝对路径、软链逃逸全部拒绝）。
  · 格式白名单：.md/.txt/.json/.csv/.docx/.xlsx 与 .pdf。其他格式如实「暂不支持」。
  · 表格不交整表：只给表头、数据行数和前若干行。
  · 单次返回按 max_chars 截断，并如实标注 truncated（不假装给了全文）。
文件不存在/为空同样如实报错——绝不编造文档内容。
"""
from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

SUPPORTED_SUFFIXES = (".md", ".txt", ".json", ".csv", ".docx", ".xlsx", ".pdf", ".png", ".jpg", ".jpeg", ".webp")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
TABLE_PREVIEW_ROWS = 20
_SUPPORTED = SUPPORTED_SUFFIXES


def normalize_doc_name(file_name: str, owner: str | None = None) -> str:
    """模型常只给文件名，有时又带上「用户名/」。工具根目录已是该用户目录时，剥掉这层前缀。

    绝对路径原样返回，交给路径护栏拒绝，不能先剥掉前导斜杠变成相对路径。
    """
    name = (file_name or "").strip().replace("\\", "/")
    if name.startswith("/") or (len(name) >= 2 and name[1] == ":"):
        return name
    while name.startswith("./"):
        name = name[2:]
    prefix = (owner or "").strip().strip("/")
    if prefix and (name == prefix or name.startswith(prefix + "/")):
        name = name[len(prefix) :].lstrip("/")
    return name


def check_inside_base(base: Path, file_name: str) -> Path:
    """路径护栏：通过返回解析后的绝对路径；越界/非法抛 ValueError。"""
    name = (file_name or "").strip()
    if not name:
        raise ValueError("文件名为空")
    target = (base / name).resolve()
    if not target.is_relative_to(base):
        raise ValueError("非法路径：只能读取文档目录内的文件")
    return target


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _decode_text(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("gbk", errors="replace")


def _table_preview(headers: list[str], rows: list[list[str]], *, sheet: str | None = None) -> str:
    title = f"工作表 {sheet}\n" if sheet else ""
    shown = rows[:TABLE_PREVIEW_ROWS]
    head = "列：" + ("、".join(headers) if any(headers) else "（无表头）")
    lines = [f"{i}. " + " | ".join(row) for i, row in enumerate(shown, 1)]
    if len(rows) > TABLE_PREVIEW_ROWS:
        tail = f"共 {len(rows)} 行，这里只给出前 {TABLE_PREVIEW_ROWS} 行"
    else:
        tail = f"共 {len(rows)} 行"
    body = "\n".join(lines)
    return f"{title}{head}\n{body}\n{tail}".strip()


def load_table_grid(
    path: Path, sheet: str | None = None
) -> tuple[list[str], list[list[str]], str | None]:
    """读出一张表：表头、数据行、工作表名。只接受 csv、xlsx 和对象数组 json。"""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        rows = list(csv.reader(io.StringIO(_decode_text(path))))
        if not rows:
            raise ValueError("表格为空")
        headers = [_cell(c) for c in rows[0]]
        data = [[_cell(c) for c in row] for row in rows[1:]]
        return headers, data, None
    if suffix == ".xlsx":
        try:
            from openpyxl import load_workbook
        except ImportError as e:
            raise RuntimeError("Excel 解析依赖未安装（openpyxl）") from e
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            names = list(book.sheetnames)
            if not names:
                raise ValueError("工作簿没有工作表")
            if sheet:
                if sheet not in names:
                    raise ValueError(f"没有工作表：{sheet}。现有：{'、'.join(names)}")
                name = sheet
            else:
                name = names[0]
            grid = [[_cell(c) for c in row] for row in book[name].iter_rows(values_only=True)]
        finally:
            book.close()
        if not grid:
            raise ValueError(f"工作表 {name} 是空的")
        return grid[0], grid[1:], name
    if suffix == ".json":
        raw = _decode_text(path).strip()
        if not raw:
            raise ValueError("表格为空")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"不是合法 JSON（{e.msg}）") from e
        rows = parsed
        if isinstance(parsed, dict):
            for key in ("rows", "data", "items"):
                if isinstance(parsed.get(key), list):
                    rows = parsed[key]
                    break
            else:
                raise ValueError("json 需要是对象数组，或包含 rows/data/items 数组")
        if not isinstance(rows, list) or not rows or not all(isinstance(item, dict) for item in rows):
            raise ValueError("json 需要是对象数组才能当表清洗")
        headers: list[str] = []
        for item in rows:
            for key in item:
                name = str(key)
                if name not in headers:
                    headers.append(name)
        data = [[_cell(item.get(h)) for h in headers] for item in rows]
        return headers, data, None
    raise ValueError("清洗只接受 csv、xlsx，或对象数组 json")


def _read_csv(path: Path) -> str:
    rows = list(csv.reader(io.StringIO(_decode_text(path))))
    if not rows:
        return ""
    headers = [_cell(c) for c in rows[0]]
    data = [[_cell(c) for c in row] for row in rows[1:]]
    return _table_preview(headers, data)


def _read_xlsx(path: Path) -> str:
    try:
        from openpyxl import load_workbook
    except ImportError as e:
        raise RuntimeError("Excel 解析依赖未安装（openpyxl）") from e
    book = load_workbook(path, read_only=True, data_only=True)
    parts: list[str] = []
    try:
        for name in book.sheetnames:
            sheet = book[name]
            grid = [[_cell(c) for c in row] for row in sheet.iter_rows(values_only=True)]
            if not grid:
                parts.append(f"工作表 {name}\n（空表）")
                continue
            parts.append(_table_preview(grid[0], grid[1:], sheet=name))
    finally:
        book.close()
    return "\n\n".join(parts).strip()


def _read_docx(path: Path) -> str:
    try:
        from docx import Document
    except ImportError as e:
        raise RuntimeError("Word 解析依赖未安装（python-docx）") from e
    doc = Document(str(path))
    parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        grid = [[_cell(cell.text) for cell in row.cells] for row in table.rows]
        if not grid:
            continue
        parts.append(_table_preview(grid[0], grid[1:]))
    return "\n".join(parts).strip()


def _read_json(path: Path) -> str:
    raw = _decode_text(path).strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        return f"不是合法 JSON（{e.msg}）。原文：\n{raw}"
    return json.dumps(parsed, ensure_ascii=False, indent=2)


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:  # 依赖缺失是部署错误，如实说
        raise RuntimeError("PDF 解析依赖未安装（pypdf）") from e
    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "") for page in reader.pages]
    return "\n".join(pages).strip()


def _pdf_images(path: Path) -> list[tuple[bytes, str]]:
    """抽出扫描页里的图片。抽不出就返回空，不假装有文字。"""
    try:
        from pypdf import PdfReader
    except ImportError:
        return []
    found: list[tuple[bytes, str]] = []
    reader = PdfReader(str(path))
    for page in reader.pages[:3]:
        images = getattr(page, "images", None) or []
        for image in images:
            data = getattr(image, "data", b"") or b""
            name = str(getattr(image, "name", "")).lower()
            if data[:2] == b"\xff\xd8" or name.endswith((".jpg", ".jpeg")):
                mime = "image/jpeg"
            elif name.endswith(".webp"):
                mime = "image/webp"
            else:
                mime = "image/png"
            if data:
                found.append((data, mime))
    return found[:3]


def _ocr_path(path: Path) -> str:
    from .tools_ocr import recognize

    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return recognize(path.read_bytes(), _IMAGE_MIME[suffix])
    text = _read_pdf(path)
    if len(text) >= 20:
        return text
    images = _pdf_images(path)
    if not images:
        return text
    pages = [recognize(data, mime) for data, mime in images]
    return "\n\n".join(page for page in pages if page).strip()


def extract_document_text(path: Path) -> str:
    """按后缀抽出可放进上下文的文本。调用方负责确认格式在白名单内。"""
    suffix = path.suffix.lower()
    if suffix == ".pdf" or suffix in IMAGE_SUFFIXES:
        return _ocr_path(path)
    if suffix == ".docx":
        return _read_docx(path)
    if suffix == ".xlsx":
        return _read_xlsx(path)
    if suffix == ".csv":
        return _read_csv(path)
    if suffix == ".json":
        return _read_json(path)
    return path.read_text(encoding="utf-8", errors="replace").strip()


def make_read_document_tool(
    *, base_dir: str, max_chars: int = 8000, owner: str | None = None
) -> Callable[..., Any]:
    """base_dir 是查找根目录。owner 有值时根目录应已是该用户的上传目录，file_name 只写文件名。"""
    base = Path(base_dir).resolve()

    def read_document(file_name: str) -> dict[str, Any]:
        name = normalize_doc_name(file_name, owner)
        target = check_inside_base(base, name)
        if not target.is_file():
            where = "当前用户上传目录" if owner else "文档目录"
            raise FileNotFoundError(f"文件不存在：{file_name}（已在{where}查找）")
        suffix = target.suffix.lower()
        if suffix not in _SUPPORTED:
            raise ValueError(f"暂不支持该格式：{suffix}（当前支持 {'/'.join(_SUPPORTED)}）")
        content = extract_document_text(target)
        if not content:
            raise ValueError(f"文档内容为空：{file_name}")
        return {
            "file_name": file_name,
            "total_chars": len(content),
            "content": content[:max_chars],
            "truncated": len(content) > max_chars,
        }

    read_document.__name__ = "read_document"
    return read_document
