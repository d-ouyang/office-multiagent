"""LLM 客户端测试（p5.1a）——MockTransport，不真调云端；密钥经 Settings 注入。"""
import httpx
import pytest

from app.core.config import settings
from app.core.llm import LlmError, LlmNotConfigured, chat, chat_stream, resolve_model


_TOOLS = [{
    "type": "function",
    "function": {"name": "query_orders", "description": "查订单", "parameters": {"type": "object", "properties": {}}},
}]


def test_chat_passes_tools_and_defaults_auto_choice(monkeypatch):
    import json

    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_OK_BODY)

    chat("deepseek-chat", [{"role": "user", "content": "hi"}], tools=_TOOLS, transport=httpx.MockTransport(handler))
    assert seen["body"]["tools"] == _TOOLS
    assert seen["body"]["tool_choice"] == "auto"

    chat("deepseek-chat", [{"role": "user", "content": "hi"}], transport=httpx.MockTransport(handler))
    assert "tools" not in seen["body"] and "tool_choice" not in seen["body"]


def test_chat_parses_tool_calls(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    body = {
        "choices": [{
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "call_1",
                    "function": {"name": "query_orders", "arguments": "{\"city\": \"上海\"}"},
                }],
            }
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    res = chat("deepseek-chat", [{"role": "user", "content": "hi"}], tools=_TOOLS, transport=httpx.MockTransport(_handler(200, body)))
    assert res.content == ""
    assert len(res.tool_calls) == 1
    call = res.tool_calls[0]
    assert (call.id, call.name, call.arguments, call.parse_error) == ("call_1", "query_orders", {"city": "上海"}, None)


def test_chat_bad_arguments_become_parse_error_not_raise(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    body = {
        "choices": [{
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "call_1",
                    "function": {"name": "query_orders", "arguments": "{\"city\": truncated"},
                }],
            }
        }],
    }
    res = chat("deepseek-chat", [{"role": "user", "content": "hi"}], tools=_TOOLS, transport=httpx.MockTransport(_handler(200, body)))
    assert res.tool_calls[0].parse_error and "解析失败" in res.tool_calls[0].parse_error
    assert res.tool_calls[0].arguments == {}


def test_chat_missing_tool_id_or_name_raises(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    body = {"choices": [{"message": {"content": "", "tool_calls": [{"id": "", "function": {"name": "x", "arguments": "{}"}}]}}]}
    with pytest.raises(LlmError, match="畸形"):
        chat("deepseek-chat", [{"role": "user", "content": "hi"}], tools=_TOOLS, transport=httpx.MockTransport(_handler(200, body)))


def test_chat_stream_accumulates_tool_call_fragments(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    finished: list = []
    res = chat_stream(
        "deepseek-chat",
        [{"role": "user", "content": "hi"}],
        on_tool_call=finished.append,
        transport=httpx.MockTransport(
            lambda req: _sse([
                '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"query_orders","arguments":"{\\"city\\": "}}]}}]}',
                '{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"上海\\"}"}}]}}]}',
                '{"choices":[{"delta":{"content":"正在查询…"}}]}',
                "[DONE]",
            ])
        ),
    )
    assert res.content == "正在查询…"
    assert len(res.tool_calls) == 1
    call = res.tool_calls[0]
    assert call.id == "call_1" and call.name == "query_orders"
    assert call.arguments == {"city": "上海"} and call.parse_error is None
    assert finished == res.tool_calls


def test_chat_stream_multiple_tool_calls_keep_index_order(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    res = chat_stream(
        "deepseek-chat",
        [{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(
            lambda req: _sse([
                '{"choices":[{"delta":{"tool_calls":[{"index":1,"id":"call_2","function":{"name":"render_chart","arguments":"{}"}}]}}]}',
                '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"query_orders","arguments":"{}"}}]}}]}',
                "[DONE]",
            ])
        ),
    )
    assert [c.id for c in res.tool_calls] == ["call_1", "call_2"]  # 按 index 排序


def test_chat_stream_no_tools_key_without_tools(monkeypatch):
    import json

    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=_IterStream([b"data: [DONE]\n\n"]))

    chat_stream("deepseek-chat", [{"role": "user", "content": "hi"}], transport=httpx.MockTransport(handler))
    assert "tools" not in seen["body"]


def test_resolve_model_ok(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    base_url, key, api_model = resolve_model("deepseek-chat")
    assert base_url == "https://api.deepseek.com/v1"
    assert key == "sk-test"
    assert api_model == "deepseek-chat"


def test_resolve_model_missing_key_is_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(LlmNotConfigured):
        resolve_model("deepseek-chat")


def test_resolve_model_unknown_model(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    with pytest.raises(LlmNotConfigured):
        resolve_model("no-such-model")


def _handler(status: int, body: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return handler


_OK_BODY = {
    "choices": [{"message": {"content": "你好"}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
}


def test_chat_ok_extracts_content_and_usage(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    res = chat(
        "deepseek-chat",
        [{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(_handler(200, _OK_BODY)),
    )
    assert res.content == "你好"
    assert (res.prompt_tokens, res.completion_tokens, res.total_tokens) == (10, 5, 15)
    assert res.model == "deepseek-chat"


def test_chat_non_200_raises(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    with pytest.raises(LlmError, match="503"):
        chat(
            "deepseek-chat",
            [{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(_handler(503, {"error": "down"})),
        )


def test_chat_malformed_payload_raises(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    with pytest.raises(LlmError, match="畸形"):
        chat(
            "deepseek-chat",
            [{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(_handler(200, {"unexpected": True})),
        )


# ---------- p6.3 流式 ----------
class _IterStream(httpx.SyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._it = iter(chunks)

    def __iter__(self):
        return self._it


def _sse(lines: list[str]) -> httpx.Response:
    body = "".join(f"data: {line}\n\n" for line in lines).encode()
    return httpx.Response(
        200, headers={"content-type": "text/event-stream"}, stream=_IterStream([body])
    )


def test_chat_stream_chunks_and_usage(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    got: list[str] = []
    res = chat_stream(
        "deepseek-chat",
        [{"role": "user", "content": "hi"}],
        on_chunk=got.append,
        transport=httpx.MockTransport(
            lambda req: _sse([
                '{"choices":[{"delta":{"content":"你好"}}]}',
                '{"choices":[{"delta":{"content":"呀"}}]}',
                '{"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}',
                "[DONE]",
            ])
        ),
    )
    assert got == ["你好", "呀"]
    assert res.content == "你好呀"
    assert (res.total_tokens, res.prompt_tokens, res.completion_tokens) == (15, 10, 5)
    assert res.model == "deepseek-chat"


def test_chat_stream_reasoning_content(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    thoughts: list[str] = []
    chat_stream(
        "deepseek-chat",
        [{"role": "user", "content": "hi"}],
        on_thought=thoughts.append,
        transport=httpx.MockTransport(
            lambda req: _sse([
                '{"choices":[{"delta":{"reasoning_content":"先想一下"}}]}',
                '{"choices":[{"delta":{"content":"答案"}}]}',
                "[DONE]",
            ])
        ),
    )
    assert thoughts == ["先想一下"]


def test_chat_stream_non_200_raises(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    with pytest.raises(LlmError, match="500"):
        chat_stream(
            "deepseek-chat",
            [{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(
                lambda req: httpx.Response(500, stream=_IterStream([b"boom"]))
            ),
        )


# ---------- p6.7b 网络重试 ----------
def test_chat_retries_transient_then_succeeds(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise httpx.ConnectError("Name or service not known")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 1}})

    res = chat("deepseek-chat", [{"role": "user", "content": "hi"}], transport=httpx.MockTransport(handler))
    assert res.content == "ok"
    assert calls["n"] == 3  # 失败 2 次 + 成功 1 次


def test_chat_no_retry_on_4xx(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(401, json={"error": "bad key"})

    with pytest.raises(LlmError, match="401"):
        chat("deepseek-chat", [{"role": "user", "content": "hi"}], transport=httpx.MockTransport(handler))
    assert calls["n"] == 1  # 鉴权错误不重试


def test_chat_stream_retry_before_first_chunk(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("Connection refused")
        return _sse(['{"choices":[{"delta":{"content":"你好"}}]}', "[DONE]"])

    got: list[str] = []
    res = chat_stream(
        "deepseek-chat", [{"role": "user", "content": "hi"}], on_chunk=got.append,
        transport=httpx.MockTransport(handler),
    )
    assert got == ["你好"]  # 首块前失败重试成功，无重复输出
    assert calls["n"] == 2


class _BrokenAfterChunk(httpx.SyncByteStream):
    """先吐一个 chunk 再断流——模拟"已出字后连接中断"。"""

    def __iter__(self):
        yield b'data: {"choices":[{"delta":{"content":"chunk1"}}]}\n\n'
        raise httpx.ReadError("connection reset by peer")


def test_chat_stream_no_retry_after_emitting(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=_BrokenAfterChunk())

    got: list[str] = []
    with pytest.raises(LlmError):
        chat_stream(
            "deepseek-chat", [{"role": "user", "content": "hi"}], on_chunk=got.append,
            transport=httpx.MockTransport(handler),
        )
    assert got == ["chunk1"]  # 已出字不重试（防重复输出）
    assert calls["n"] == 1


def test_chat_includes_reasoning_effort_only_when_set(monkeypatch):
    import json

    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_OK_BODY)

    chat(
        "deepseek-chat",
        [{"role": "user", "content": "hi"}],
        reasoning_effort="max",
        transport=httpx.MockTransport(handler),
    )
    assert seen["body"]["reasoning_effort"] == "max"
    chat(
        "deepseek-chat",
        [{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(handler),
    )
    assert "reasoning_effort" not in seen["body"]
