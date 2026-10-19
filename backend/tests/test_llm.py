"""LLM 客户端测试（p5.1a）——MockTransport，不真调云端；密钥经 Settings 注入。"""
import httpx
import pytest

from app.core.config import settings
from app.core.llm import LlmError, LlmNotConfigured, chat, resolve_model


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
