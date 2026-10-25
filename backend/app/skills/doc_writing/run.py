"""doc_writing 的可选编排逻辑（run.py）。

缺省行为是"通用 ReAct + 受限工具集"，run.py 只在需要自定义时才存在。
这里做三件 skill 自己的事，**不重新实现落盘逻辑**（原子能力仍在 tools_write.py）：
  1. format 归一化与白名单校验（markdown→md、word→docx …）
  2. title / content 必填校验
  3. 校验通过后委托给受限工具集里的 write_document

返回统一结构 {"ok": bool, "output"/"error"}，失败不抛异常——让上层能如实降级。
"""
from __future__ import annotations

from typing import Any

from ..base import SkillContext

FORMATS = ("md", "docx", "pdf", "pptx")

_ALIASES = {
    "markdown": "md",
    "word": "docx",
    "wps": "docx",
    "powerpoint": "pptx",
    "ppt": "pptx",
}


def run(ctx: SkillContext, **kwargs: Any) -> dict[str, Any]:
    """把结论写成文档。成功返回 {"ok": True, "output": 工具原始返回}。"""
    title = str(kwargs.get("title") or "").strip()
    content = str(kwargs.get("content") or "").strip()
    raw_format = str(kwargs.get("format") or "md").strip().lower()
    fmt = _ALIASES.get(raw_format, raw_format)

    if not title:
        return {"ok": False, "error": "缺少 title：文档必须有标题"}
    if not content:
        return {
            "ok": False,
            "error": "content 为空：正文不能为空，且数字必须来自此前的工具结果",
        }
    if fmt not in FORMATS:
        return {
            "ok": False,
            "error": f"format 只支持 {'/'.join(FORMATS)}（收到 {raw_format or '空'}）；"
            "要画图请用 render_chart，要流程图请用 render_flow",
        }
    if ctx.tools is None or not ctx.tools.has("write_document"):
        return {"ok": False, "error": "CAPABILITY_MISSING: 当前 skill 未获得 write_document 工具"}

    result = ctx.tools.call(
        "write_document",
        title=title,
        content=content,
        format=fmt,
        clean_id=kwargs.get("clean_id"),
        image_file=kwargs.get("image_file"),
    )
    if not result.ok:
        return {"ok": False, "error": result.error}
    return {"ok": True, "output": result.output}
