"""逐模型点测 OpenAI 兼容 tools / tool_calls（只读云端调用，不改配置）。

用法：PYTHONPATH=/app python /app/scripts/probe_tool_calls.py [--model ID]
输出仅为能力 JSON，不包含密钥。每模型最多非流式/流式各一次，max_tokens=256。
"""
from __future__ import annotations

import argparse
import json
import time
from typing import Any

import httpx

from app.core.llm import resolve_model
from app.core.model_registry import load_registry

TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询指定城市的天气",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "城市名"}},
            "required": ["city"],
            "additionalProperties": False,
        },
    },
}]
MESSAGES = [
    {"role": "system", "content": "你必须调用 get_weather 工具，不要直接回答。"},
    {"role": "user", "content": "查询上海天气。"},
]


def _valid_calls(calls: Any) -> bool:
    if not isinstance(calls, list) or not calls:
        return False
    for call in calls:
        fn = call.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "")
        except (TypeError, ValueError):
            return False
        if not call.get("id") or fn.get("name") != "get_weather" or not isinstance(args, dict):
            return False
    return True


def probe(model_id: str, timeout: float = 60) -> dict[str, Any]:
    base_url, api_key, api_model = resolve_model(model_id)
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": api_model,
        "messages": MESSAGES,
        "tools": TOOLS,
        "tool_choice": "auto",
        "temperature": 0,
        "max_tokens": 256,
    }
    result: dict[str, Any] = {"id": model_id, "supports_tools": None, "stream_tool_calls": None}
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        with httpx.Client(timeout=timeout) as client:
            started = time.monotonic()
            resp = client.post(url, json=payload, headers=headers)
            result["nonstream_http"] = resp.status_code
            result["nonstream_ms"] = round((time.monotonic() - started) * 1000)
            if resp.status_code == 200:
                message = resp.json()["choices"][0]["message"]
                result["supports_tools"] = _valid_calls(message.get("tool_calls"))
            else:
                result["supports_tools"] = False
                result["nonstream_error"] = resp.text[:160]

            stream_payload = {**payload, "stream": True, "stream_options": {"include_usage": True}}
            calls: dict[int, dict[str, Any]] = {}
            started = time.monotonic()
            with client.stream("POST", url, json=stream_payload, headers=headers) as resp:
                result["stream_http"] = resp.status_code
                if resp.status_code == 200:
                    for line in resp.iter_lines():
                        if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                            continue
                        try:
                            obj = json.loads(line[5:].strip())
                        except ValueError:
                            continue
                        for choice in obj.get("choices") or []:
                            for part in (choice.get("delta") or {}).get("tool_calls") or []:
                                index = int(part.get("index", 0))
                                slot = calls.setdefault(index, {"id": "", "function": {"name": "", "arguments": ""}})
                                if part.get("id"):
                                    slot["id"] += part["id"]
                                fn = part.get("function") or {}
                                for key in ("name", "arguments"):
                                    if fn.get(key):
                                        slot["function"][key] += fn[key]
                    result["stream_tool_calls"] = _valid_calls(list(calls.values()))
                else:
                    result["stream_tool_calls"] = False
                    result["stream_error"] = resp.read().decode("utf-8", "replace")[:160]
            result["stream_ms"] = round((time.monotonic() - started) * 1000)
    except Exception as exc:  # 点测失败不能误标为支持；保留错误类型供复核
        result["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append", dest="models")
    args = parser.parse_args()
    ids = args.models or [m.id for m in load_registry()["models"] if m.in_dialogue and m.enabled]
    for model_id in ids:
        print(json.dumps(probe(model_id), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
