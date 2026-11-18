"""LLM 客户端测试（p5.1a）——MockTransport，不真调云端；密钥经 Settings 注入。"""
import httpx
import pytest

from app.core.config import settings
from app.core.llm import (
    LlmError,
    LlmNotConfigured,
    _is_transient,
    _retry_delay,
    _status_code_of,
    chat,
    chat_stream,
    resolve_model,
)


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


# ---------- p5.1 重试覆盖面补全（429/500）+ 参数配置化 ----------
def test_status_code_of_parses_llm_error():
    assert _status_code_of(LlmError("LLM 返回 429: too many requests")) == 429
    assert _status_code_of(LlmError("LLM 返回 502: bad gateway")) == 502
    assert _status_code_of(LlmError("LLM 请求失败：ConnectError: x")) is None


def test_transient_covers_429_and_500_but_not_other_4xx():
    assert _is_transient(LlmError("LLM 返回 429: rate limited"))
    assert _is_transient(LlmError("LLM 返回 500: internal error"))
    assert _is_transient(LlmError("LLM 返回 502: bad gateway"))
    assert not _is_transient(LlmError("LLM 返回 401: bad key"))
    assert not _is_transient(LlmError("LLM 返回 400: bad request"))


def test_retry_delay_429_uses_longer_backoff(monkeypatch):
    monkeypatch.setattr(settings, "llm_retry_backoff", 0.8)
    monkeypatch.setattr(settings, "llm_retry_backoff_429", 2.0)
    assert _retry_delay(LlmError("LLM 返回 429: x"), 0) == 2.0
    assert _retry_delay(LlmError("LLM 返回 429: x"), 1) == 4.0
    assert _retry_delay(LlmError("LLM 返回 502: x"), 0) == 0.8


def test_chat_retries_429_then_succeeds(monkeypatch):
    """multi 层内并行打同一模型时最容易撞 429——必须能退避重试救回。"""
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    sleeps: list[float] = []
    monkeypatch.setattr("app.core.llm.time.sleep", sleeps.append)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 1}})

    res = chat("deepseek-chat", [{"role": "user", "content": "hi"}], transport=httpx.MockTransport(handler))
    assert res.content == "ok"
    assert calls["n"] == 3  # 429 两次 + 成功一次
    assert sleeps == [2.0, 4.0]  # 429 走更长退避基数，不是网络错误的 0.8


def test_chat_retries_500_then_succeeds(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    monkeypatch.setattr("app.core.llm.time.sleep", lambda _s: None)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, json={"error": "internal"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 1}})

    res = chat("deepseek-chat", [{"role": "user", "content": "hi"}], transport=httpx.MockTransport(handler))
    assert res.content == "ok"
    assert calls["n"] == 2


def test_chat_no_retry_on_400(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(400, json={"error": "bad request"})

    with pytest.raises(LlmError, match="400"):
        chat("deepseek-chat", [{"role": "user", "content": "hi"}], transport=httpx.MockTransport(handler))
    assert calls["n"] == 1  # 参数错误重试无意义


def test_chat_max_retries_zero_disables_retry(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    monkeypatch.setattr(settings, "llm_max_retries", 0)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(502, json={"error": "bad gateway"})

    with pytest.raises(LlmError, match="502"):
        chat("deepseek-chat", [{"role": "user", "content": "hi"}], transport=httpx.MockTransport(handler))
    assert calls["n"] == 1  # 配置关闭后不再重试


def test_chat_stream_retries_429_before_first_chunk(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    monkeypatch.setattr("app.core.llm.time.sleep", lambda _s: None)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return _sse(['{"choices":[{"delta":{"content":"你好"}}]}', "[DONE]"])

    got: list[str] = []
    chat_stream(
        "deepseek-chat", [{"role": "user", "content": "hi"}], on_chunk=got.append,
        transport=httpx.MockTransport(handler),
    )
    assert got == ["你好"]  # 首块前 429 可重试，无重复输出
    assert calls["n"] == 2


# --------------------------------------------------------------------------- #
# v2.2.0-p1.4（B1）：LLM 网关收口开关（settings.llm_gateway_url）
# --------------------------------------------------------------------------- #


def test_resolve_model_gateway_rewrite(monkeypatch):
    """llm_gateway_url 非空：base_url 重写为网关、key 重写为服务间密钥，api_model 不变。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "llm_gateway_url", "http://gateway:3000/llm/v1")
    monkeypatch.setattr(settings, "internal_shared_secret", "it-secret")
    base_url, api_key, api_model = resolve_model("deepseek-chat")
    assert base_url == "http://gateway:3000/llm/v1"
    assert api_key == "it-secret"
    assert api_model == "deepseek-chat"


def test_resolve_model_gateway_without_secret_fails_closed(monkeypatch):
    """网关开着但服务间密钥未配置：响亮失败，绝不静默直连。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "llm_gateway_url", "http://gateway:3000/llm/v1")
    monkeypatch.setattr(settings, "internal_shared_secret", "")
    with pytest.raises(LlmNotConfigured, match="INTERNAL_SHARED_SECRET"):
        resolve_model("deepseek-chat")


def test_resolve_model_direct_mode_unchanged(monkeypatch):
    """开关留空（B1 之前现状）：直连行为零变化。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "llm_gateway_url", "")
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    base_url, api_key, api_model = resolve_model("deepseek-chat")
    assert base_url == "https://api.deepseek.com/v1"
    assert api_key == "sk-test"
