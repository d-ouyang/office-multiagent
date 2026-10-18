"""日志与可观测性测试（设计文档 §十八）。

验证：JSON 格式化器能把 extra 结构化字段摊平进日志、setup_logging 不抛、
语义化辅助函数（agent_step / token_audit）可调用。
"""
import json
import logging

from app.core.logging import (
    CorrelationMiddleware,
    _JsonFormatter,
    log_agent_step,
    log_token_audit,
    setup_logging,
)


def test_json_formatter_flattens_extra():
    fmt = _JsonFormatter()
    rec = logging.LogRecord("agent", logging.INFO, "path", 1, "agent_step", None, None)
    rec.correlation_id = "cid-1"
    rec.subtask_id = "s1"
    rec.agent = "planner"
    rec.action = "plan"
    out = fmt.format(rec)
    parsed = json.loads(out)
    assert parsed["msg"] == "agent_step"
    assert parsed["subtask_id"] == "s1"
    assert parsed["agent"] == "planner"
    assert parsed["correlation_id"] == "cid-1"


def test_setup_logging_and_helpers_no_error():
    setup_logging()  # 不应抛
    log_agent_step("s1", "planner", "plan", note="ok")
    log_token_audit(1, "deepseek-chat", reserve=100, settle=90)
