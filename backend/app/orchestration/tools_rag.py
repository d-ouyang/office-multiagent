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
    actor: str | None = None,
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
        # persist=false：走 RAG 完整检索/生成，但不写入 RAG 会话和额度。
        # 用量随 usage 带回，由办公任务结算进当前用户钱包。
        try:
            with httpx.Client(timeout=timeout, transport=transport) as client:
                resp = client.post(url, json={"question": q, "persist": False}, headers=headers)
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
                "chunk_id": s.get("chunk_id"),
                "rerank_score": s.get("rerank_score"),
                "vector_similarity": s.get("vector_similarity"),
            }
            for s in (data.get("sources") or [])
        ]
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return {
            "answer": data.get("answer", ""),
            "route": data.get("route", ""),
            "intent": data.get("intent", ""),
            "sources": sources,
            "source_count": len(sources),
            "usage": {
                "input_tokens": int(usage.get("input_tokens") or 0),
                "output_tokens": int(usage.get("output_tokens") or 0),
            },
            "grounded": data.get("grounded"),
            "low_confidence": data.get("low_confidence"),
            "qa_trace": data.get("qa_trace"),
            "persisted": data.get("persisted"),
            "rag_username": username,
            "office_username": actor or username,
            "identity_mismatch": bool(actor and actor != username),
            "note": (
                "未写入知识库自己的会话。重排分在 sources.rerank_score，依据在 grounded。"
                "usage 会记入本轮办公消耗，不要再向用户报一份知识库侧的账单。"
            ),
        }

    rag_retrieve.__name__ = "rag_retrieve"
    return rag_retrieve
