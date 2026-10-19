"""rag_retrieve 工具（p5.1a）——把 RAG 当外部工具复用（设计文档 §12.3：不重写，只接）。

走 RAG 后端内部接口 `POST /api/v1/qa/ask`：
  · 网关证明 `X-Internal-Auth` = office 域密钥（须与 RAG 后端 OFFICE_GATEWAY_SHARED_SECRET
    同值，rag p4.11 已认）；注入 `X-Username`（RAG 按 username 解析身份，须能在其 user 表落地）。
  · RAG dev 模式不验证明——本工具不带/带证明都能通，生产 gateway 模式必须配密钥。
失败（网络/非 200）抛 RuntimeError，由 ToolRegistry 转结构化错误如实告知，绝不编造检索结果。
httpx transport 可注入（测试 MockTransport，不出网）。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx


def make_rag_retrieve_tool(
    *,
    base_url: str,
    internal_secret: str = "",
    username: str = "office-service",
    timeout: float = 60.0,
    transport: httpx.BaseTransport | None = None,
) -> Callable[..., Any]:
    def rag_retrieve(query: str) -> dict[str, Any]:
        q = (query or "").strip()
        if not q:
            raise ValueError("检索问题为空")
        headers = {"Content-Type": "application/json"}
        if internal_secret:
            headers["X-Internal-Auth"] = internal_secret
            headers["X-Username"] = quote(username, safe="")
        url = base_url.rstrip("/") + "/api/v1/qa/ask"
        try:
            with httpx.Client(timeout=timeout, transport=transport) as client:
                resp = client.post(url, json={"question": q}, headers=headers)
        except httpx.HTTPError as e:
            raise RuntimeError(f"知识库检索失败：{type(e).__name__}: {e}") from e
        if resp.status_code != 200:
            raise RuntimeError(f"知识库检索返回 {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        sources = [
            {
                "index": s.get("index"),
                "source": s.get("source"),
                "file_name": s.get("file_name"),
                "snippet": s.get("snippet"),
            }
            for s in (data.get("sources") or [])
        ]
        return {
            "answer": data.get("answer", ""),
            "route": data.get("route", ""),
            "sources": sources,
            "source_count": len(sources),
        }

    rag_retrieve.__name__ = "rag_retrieve"
    return rag_retrieve
