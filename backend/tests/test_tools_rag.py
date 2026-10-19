"""rag_retrieve 工具测试（p5.1a）——MockTransport，不出网；断言证明头/身份头/错误路径。"""
import json
from urllib.parse import quote

import httpx
import pytest

from app.orchestration.tools_rag import make_rag_retrieve_tool

_OK_BODY = {
    "session_id": "s1",
    "answer": "年假 5 天",
    "intent": "rag",
    "route": "rag_qa",
    "sources": [
        {"index": 1, "source": "upload/a.md", "file_name": "a.md", "snippet": "片段"},
        {"index": 2, "source": "upload/b.md", "file_name": "b.md", "snippet": "片段2"},
    ],
}


def _capture_handler(status: int = 200, body: dict | None = None):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(status, json=body if body is not None else {})

    return handler, captured


def test_rag_retrieve_ok_with_proof_headers():
    handler, captured = _capture_handler(200, _OK_BODY)
    tool = make_rag_retrieve_tool(
        base_url="http://rag", internal_secret="office-secret", username="张三",
        transport=httpx.MockTransport(handler),
    )
    out = tool("公司年假几天")
    assert out["answer"] == "年假 5 天"
    assert out["route"] == "rag_qa"
    assert out["source_count"] == 2
    assert out["sources"][0]["file_name"] == "a.md"
    req = captured[0]
    assert req.url.path == "/api/v1/qa/ask"
    assert req.headers["x-internal-auth"] == "office-secret"
    assert req.headers["x-username"] == quote("张三", safe="")
    assert json.loads(req.content)["question"] == "公司年假几天"


def test_rag_retrieve_no_secret_sends_no_proof():
    handler, captured = _capture_handler(200, _OK_BODY)
    tool = make_rag_retrieve_tool(
        base_url="http://rag", internal_secret="", transport=httpx.MockTransport(handler)
    )
    tool("q")
    req = captured[0]
    assert "x-internal-auth" not in req.headers
    assert "x-username" not in req.headers


def test_rag_retrieve_non_200_raises():
    handler, _ = _capture_handler(503, {"detail": "down"})
    tool = make_rag_retrieve_tool(
        base_url="http://rag", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RuntimeError, match="503"):
        tool("q")


def test_rag_retrieve_empty_query_raises():
    tool = make_rag_retrieve_tool(base_url="http://rag")
    with pytest.raises(ValueError, match="为空"):
        tool("   ")
