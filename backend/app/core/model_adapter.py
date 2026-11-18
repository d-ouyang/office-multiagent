"""ModelAdapter 契约（v2.2.0-p1.0 / Phase A1）。

为什么要有这一层（路线文档 §4.1「6 个版本化契约」之一）：
- `llm.py` 的 chat/chat_stream 是 **OpenAI 兼容直连**的实现细节；契约化后
  换实现（LiteLLM Proxy、本地 Ollama 直连、多活 fallback）不改任何调用点——
  brain/react 继续 `from ..core.llm import chat`，门面在 llm 模块内转发到当前 adapter。
- 测试注入 `FakeModelAdapter`（脚本化 LlmResult 序列），比 httpx MockTransport
  更贴业务层：不模拟 HTTP 细节，直接模拟「模型决定了什么」。
- Phase B 接 LiteLLM 时只需实现一个 adapter 并 set/注册，不改 brain 一行。

红线（等价重构）：
- 契约层只做转发与注入，不吞异常、不加逻辑、不改默认行为；
- 默认 adapter = OpenAICompatAdapter，即原 llm.chat/chat_stream 原样委托；
- 生产代码不走 set_adapter（注入仅测试用；运行时切换走 settings，Phase B 落）。

契约面（与现有调用能力一致，不做阉割版的 invoke()）：
- chat / chat_stream 双通道（流式回调、tool_calls 增量、usage 结算）；
- budget 以 max_tokens/timeout 传参先占位，Phase B 升级为结构化预算；
- 响应统一 `LlmResult`（content/usage/tool_calls），定义仍在 llm.py（单一出处）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # 运行时零依赖 llm 模块（llm 顶部 import 本模块的门面取 adapter，不能反向循环）
    from .llm import LlmResult


@runtime_checkable
class ModelAdapter(Protocol):
    """模型适配器契约：一次非流式 + 一次流式调用，签名与 llm.chat/chat_stream 对齐。"""

    name: str

    def chat(self, model_id: str, messages: list[dict[str, str]], **kwargs: Any) -> "LlmResult": ...

    def chat_stream(self, model_id: str, messages: list[dict[str, str]], **kwargs: Any) -> "LlmResult": ...


class OpenAICompatAdapter:
    """默认实现：原样委托 llm 模块内的直连实现（等价重构，行为零变化）。"""

    name = "openai"

    def chat(self, model_id: str, messages: list[dict[str, str]], **kwargs: Any) -> "LlmResult":
        from . import llm

        return llm._chat_impl(model_id, messages, **kwargs)  # noqa: SLF001 - 门面委托即本意

    def chat_stream(self, model_id: str, messages: list[dict[str, str]], **kwargs: Any) -> "LlmResult":
        from . import llm

        return llm._chat_stream_impl(model_id, messages, **kwargs)  # noqa: SLF001 - 同上


class FakeModelAdapter:
    """测试用假模型：脚本化返回序列，逐次弹出；记录每次调用供断言。

    script 项支持三种形态：
    - `LlmResult`：原样返回；
    - `str`：包装为 `LlmResult(content=str)`（JSON 文本协议测试最常用）；
    - `callable(model_id, messages, **kwargs) -> LlmResult | str`：按入参分支
      （模拟 ReAct 第 N 轮的决策）。
    脚本耗尽再被调用 → AssertionError（测试里模型被多调一轮就是 bug，不能静默循环）。
    chat_stream 委托 chat（Fake 不模拟流式分块，只验证终值与回调契约由真实现负责）。
    """

    name = "fake"

    def __init__(self, script: list[Any] | None = None) -> None:
        self.script: list[Any] = list(script or [])
        self.calls: list[dict[str, Any]] = []

    def chat(self, model_id: str, messages: list[dict[str, str]], **kwargs: Any) -> "LlmResult":
        from .llm import LlmResult

        self.calls.append({"model_id": model_id, "messages": list(messages), "kwargs": set(kwargs)})
        if not self.script:
            raise AssertionError(f"FakeModelAdapter 脚本耗尽（第 {len(self.calls)} 次调用，超出预期轮数）")
        item = self.script.pop(0)
        if callable(item):
            item = item(model_id, messages, **kwargs)
        if isinstance(item, str):
            item = LlmResult(content=item)
        return item

    def chat_stream(self, model_id: str, messages: list[dict[str, str]], **kwargs: Any) -> "LlmResult":
        return self.chat(model_id, messages, **kwargs)


_active_adapter: ModelAdapter | None = None
_default_adapter: OpenAICompatAdapter | None = None


def set_adapter(adapter: ModelAdapter) -> ModelAdapter:
    """注入运行期 adapter（测试用）。用完必须 reset，否则跨用例泄漏。"""
    global _active_adapter
    _active_adapter = adapter
    return adapter


def reset_adapter() -> None:
    global _active_adapter
    _active_adapter = None


def get_adapter() -> ModelAdapter:
    """当前 adapter：显式注入优先（测试），缺省 OpenAI 兼容直连。"""
    global _default_adapter
    if _active_adapter is not None:
        return _active_adapter
    if _default_adapter is None:
        _default_adapter = OpenAICompatAdapter()
    return _default_adapter
