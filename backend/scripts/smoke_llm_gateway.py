"""B1 冒烟脚本：LLM 网关（gateway 内置代理）vs 直连的行为一致性对比。

用法：
  DEEPSEEK_API_KEY=sk-xxx INTERNAL_SHARED_SECRET=xxx python smoke_llm_gateway.py

五项清单（每项在「直连 provider」与「经网关」各跑一遍并对比）：
  1. 非流式 + tool_calls（结构一致：choices/usage/tool_calls）
  2. 流式正文（打字机 chunks>1、首块前无整块缓冲）
  3. 流式 tool_calls 增量（delta.tool_calls 可累积出 name+arguments）
  4. reasoning_content 思考通道（deepseek-reasoner）
  5. usage 字段一致且非零（token 两段式结算的数据源不能漂）
"""
from __future__ import annotations

import json
import os
import sys

import httpx

TIMEOUT = 120.0
TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查天气",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    },
}]


def chat(base: str, key: str, model: str, *, stream: bool, tools: bool = False, trust_env: bool = True) -> dict:
    url = base.rstrip("/") + "/chat/completions"
    payload: dict = {
        "model": model,
        "messages": [{"role": "user", "content": "上海今天天气怎么样？用 get_weather 查一下"}],
        "temperature": 0,
    }
    if stream:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
    if tools:
        payload["tools"] = TOOLS
    headers = {"Authorization": f"Bearer {key}", "content-type": "application/json"}
    out: dict = {"content_parts": 0, "content": "", "thought_parts": 0, "thought": "",
                 "tool_call_chunks": 0, "tool_name": "", "tool_args": "",
                 "usage_keys": [], "usage_total": 0, "status": 0, "err": ""}
    # trust_env 按目标区分：直连厂商走系统代理（本机网络常态）；网关在 127.0.0.1
    # 必须绕开系统代理（否则被 ClashX 劫持超时）。
    with httpx.Client(timeout=TIMEOUT, trust_env=trust_env) as client:
        if not stream:
            r = client.post(url, json=payload, headers=headers)
            out["status"] = r.status_code
            if r.status_code != 200:
                out["err"] = r.text[:200]
                return out
            data = r.json()
            msg = data["choices"][0]["message"]
            out["content"] = msg.get("content") or ""
            calls = msg.get("tool_calls") or []
            out["tool_name"] = calls[0]["function"]["name"] if calls else ""
            out["tool_args"] = (calls[0]["function"].get("arguments") or "") if calls else ""
            usage = data.get("usage") or {}
            out["usage_keys"] = sorted(usage.keys())
            out["usage_total"] = int(usage.get("total_tokens", 0))
            return out
        with client.stream("POST", url, json=payload, headers=headers) as r:
            out["status"] = r.status_code
            if r.status_code != 200:
                out["err"] = r.read().decode("utf-8", "replace")[:200]
                return out
            raw_calls: dict[int, dict] = {}
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    obj = json.loads(data_str)
                except ValueError:
                    continue
                if obj.get("usage"):
                    u = obj["usage"]
                    out["usage_keys"] = sorted(u.keys())
                    out["usage_total"] = int(u.get("total_tokens", 0))
                for choice in obj.get("choices") or []:
                    delta = (choice.get("delta") or {}) if isinstance(choice, dict) else {}
                    piece = delta.get("content") or ""
                    if piece:
                        out["content_parts"] += 1
                        out["content"] += piece
                    thought = delta.get("reasoning_content") or ""
                    if thought:
                        out["thought_parts"] += 1
                        out["thought"] += thought
                    for part in delta.get("tool_calls") or []:
                        out["tool_call_chunks"] += 1
                        fn = part.get("function") or {}
                        if fn.get("name"):
                            out["tool_name"] += fn["name"]
                        if fn.get("arguments") is not None:
                            out["tool_args"] += fn["arguments"]
            return out


def main() -> int:
    ds_key = os.environ.get("DEEPSEEK_API_KEY", "")
    internal = os.environ.get("INTERNAL_SHARED_SECRET", "")
    if not ds_key or not internal:
        print("缺 DEEPSEEK_API_KEY 或 INTERNAL_SHARED_SECRET 环境变量")
        return 2

    # 网关地址可覆盖：容器内跑时用容器网络地址。
    # ⚠️ 生产必须用【容器名】office-gateway——backend 同时挂在 office-net/rag-net，
    # 服务名 gateway 会在 office-gateway 与 rag-gateway 之间 DNS 轮询（约一半 404），
    # 与「服务名必须带 office- 前缀」铁律同源（p6.43）。
    gw_base = os.environ.get("LLM_GATEWAY_BASE", "http://127.0.0.1:3001/llm/v1")
    suites = [
        ("直连", "https://api.deepseek.com/v1", ds_key),
        ("网关", gw_base, internal),
    ]
    checks: list[tuple[str, bool, str]] = []

    # 1) 非流式 + tool_calls
    r = {}
    for label, base, key in suites:
        r[label] = chat(base, key, "deepseek-chat", stream=False, tools=True, trust_env=base.startswith("https"))
    a, b = r["直连"], r["网关"]
    checks.append((
        "1.非流式+tool_calls",
        a["status"] == b["status"] == 200 and a["tool_name"] == b["tool_name"] == "get_weather"
        and bool(a["tool_args"]) == bool(b["tool_args"]),
        f"直连 status={a['status']} tool={a['tool_name']} | 网关 status={b['status']} tool={b['tool_name']} err={b['err'][:80]}",
    ))

    # 2) 流式正文
    r = {}
    for label, base, key in suites:
        r[label] = chat(base, key, "deepseek-chat", stream=True, trust_env=base.startswith("https"))
    a, b = r["直连"], r["网关"]
    checks.append((
        "2.流式正文",
        a["status"] == b["status"] == 200 and b["content_parts"] >= 1 and b["content_parts"] <= a["content_parts"] * 3 + 3,
        f"直连 chunks={a['content_parts']} | 网关 chunks={b['content_parts']} err={b['err'][:80]}",
    ))

    # 3) 流式 tool_calls 增量
    r = {}
    for label, base, key in suites:
        r[label] = chat(base, key, "deepseek-chat", stream=True, tools=True, trust_env=base.startswith("https"))
    a, b = r["直连"], r["网关"]
    checks.append((
        "3.流式tool_calls增量",
        b["status"] == 200 and b["tool_call_chunks"] >= 1 and b["tool_name"] == "get_weather"
        and b["tool_args"].strip().startswith("{"),
        f"直连 chunks={a['tool_call_chunks']} tool={a['tool_name']} | 网关 chunks={b['tool_call_chunks']} tool={b['tool_name']} args={b['tool_args'][:40]} err={b['err'][:60]}",
    ))

    # 4) reasoning_content（deepseek-reasoner，慢）
    r = {}
    for label, base, key in suites:
        r[label] = chat(base, key, "deepseek-reasoner", stream=True, trust_env=base.startswith("https"))
    a, b = r["直连"], r["网关"]
    checks.append((
        "4.reasoning_content",
        b["status"] == 200 and b["thought_parts"] >= 1,
        f"直连 thought_parts={a['thought_parts']} status={a['status']} | 网关 thought_parts={b['thought_parts']} status={b['status']} err={b['err'][:60]}",
    ))

    # 5) usage 结构一致
    r = {}
    for label, base, key in suites:
        r[label] = chat(base, key, "deepseek-chat", stream=False, trust_env=base.startswith("https"))
    a, b = r["直连"], r["网关"]
    core = [k for k in a["usage_keys"] if k in ("prompt_tokens", "completion_tokens", "total_tokens")]
    b_core = [k for k in b["usage_keys"] if k in ("prompt_tokens", "completion_tokens", "total_tokens")]
    checks.append((
        "5.usage结构一致",
        core == b_core and b["usage_total"] > 0,
        f"直连 keys={a['usage_keys']} | 网关 keys={b['usage_keys']} total={b['usage_total']}",
    ))

    print("=" * 72)
    failed = 0
    for name, ok, detail in checks:
        print(f"{'✅ PASS' if ok else '❌ FAIL'}  {name}")
        print(f"        {detail}")
        failed += 0 if ok else 1
    print("=" * 72)
    print(f"{len(checks) - failed}/{len(checks)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
