"""测试全局约定（conftest）。

单测确定性铁律：**单测绝不真调云端 LLM**。backend/.env 配了真实 key 也不许用——
本 fixture 强制清空 key，使 make_brain 一律回落 StubBrain（确定性基线）。
真 LLM 的验证走显式 smoke（脚本/端到端），不进 pytest。
需要 LLM 客户端行为的测试，在自己用例里显式 monkeypatch key（会覆盖本 fixture）。
"""
import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    monkeypatch.setattr(settings, "siliconflow_api_key", "")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    yield
