"""read_document 工具（p5.2）——读取文档目录内的文本内容（.md/.txt/.pdf）。

硬护栏（fail-closed）：
  · 路径穿越防护：解析后的真实路径必须仍在文档目录内（`..`、绝对路径、软链逃逸全部拒绝）。
  · 格式白名单：仅 .md/.txt（直读）与 .pdf（pypdf 抽文本）；其他格式如实"暂不支持"。
  · 单次返回按 max_chars 截断，并如实标注 truncated（不假装给了全文）。
文件不存在/为空同样如实报错——绝不编造文档内容。
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

_SUPPORTED = (".md", ".txt", ".pdf")


def check_inside_base(base: Path, file_name: str) -> Path:
    """路径护栏：通过返回解析后的绝对路径；越界/非法抛 ValueError。"""
    name = (file_name or "").strip()
    if not name:
        raise ValueError("文件名为空")
    target = (base / name).resolve()
    if not target.is_relative_to(base):
        raise ValueError("非法路径：只能读取文档目录内的文件")
    return target


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:  # 依赖缺失是部署错误，如实说
        raise RuntimeError("PDF 解析依赖未安装（pypdf）") from e
    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "") for page in reader.pages]
    return "\n".join(pages).strip()


def make_read_document_tool(*, base_dir: str, max_chars: int = 8000) -> Callable[..., Any]:
    base = Path(base_dir).resolve()

    def read_document(file_name: str) -> dict[str, Any]:
        target = check_inside_base(base, file_name)
        if not target.is_file():
            raise FileNotFoundError(f"文件不存在：{file_name}")
        suffix = target.suffix.lower()
        if suffix not in _SUPPORTED:
            raise ValueError(f"暂不支持该格式：{suffix}（当前支持 {'/'.join(_SUPPORTED)}）")
        if suffix == ".pdf":
            content = _read_pdf(target)
        else:
            content = target.read_text(encoding="utf-8", errors="replace").strip()
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
