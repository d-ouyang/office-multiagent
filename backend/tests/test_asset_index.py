"""2.1.0 P0 轻档：追问任务注入前任务产物索引（clean_id）——提取与格式化。"""
import json

from app.api.routes import _build_asset_index


def _msg(trace_events):
    return {"role": "assistant", "trace": json.dumps(trace_events, ensure_ascii=False)}


def _observation(clean_id, group_by, metric, rows):
    obs = json.dumps(
        {
            "clean_id": clean_id,
            "group_by": group_by,
            "metric": metric,
            "row_count": rows,
            "rows": [["x", 1]],
        },
        ensure_ascii=False,
    )
    return {"type": "observation", "data": {"tool_id": "t1", "text": obs}}


def test_extracts_clean_id_from_history_trace():
    prior = [_msg([_observation("g-aaa", "store_name", "sum_pay", 8)])]
    idx = _build_asset_index(prior)
    assert "g-aaa" in idx
    assert "store_name" in idx
    assert "sum_pay" in idx
    assert "无需重新查询" in idx


def test_dedupes_and_caps_at_five():
    events = []
    for i in range(8):
        events.append(_observation(f"g-{i}", "store_name", "sum_pay", 8))
    prior = [_msg(events)]
    idx = _build_asset_index(prior)
    assert idx.count("- g-") == 5  # 上限 5 条
    assert "g-7" in idx  # 最新优先


def test_skips_bad_json_and_empty():
    prior = [
        {"role": "assistant", "trace": "not-json{{"},
        {"role": "assistant", "trace": json.dumps([{"type": "observation", "data": {"text": "纯文本观察"}}])},
        {"role": "user", "trace": json.dumps([_observation("g-skip", "x", "y", 1)])},  # user 消息不算
    ]
    assert _build_asset_index(prior) == ""


def test_metrics_list_format():
    obs = json.dumps(
        {"clean_id": "g-m1", "group_by": "store_name", "metrics": ["count", "sum_pay"], "row_count": 4},
        ensure_ascii=False,
    )
    prior = [_msg([{"type": "observation", "data": {"tool_id": "t", "text": obs}}])]
    idx = _build_asset_index(prior)
    assert "count、sum_pay" in idx


def test_paused_budget_in_resumable_whitelist():
    """2.1.0-p1.4 生产 hotfix 回归：paused_budget 必须在 /resume 白名单（漏加导致点继续报 NOT_RESUMABLE）。"""
    from app.api.routes import _RESUMABLE

    assert "paused_budget" in _RESUMABLE
    # paused_input 走 /answer 端点，不在 /resume 白名单是有意设计
    assert "paused_input" not in _RESUMABLE


def test_paused_budget_in_resumable_whitelist():
    """2.1.0-p1.4 生产 hotfix 回归：paused_budget 必须在 /resume 白名单（漏加导致点继续报 NOT_RESUMABLE）。"""
    from app.api.routes import _RESUMABLE

    assert "paused_budget" in _RESUMABLE
    # paused_input 走 /answer 端点，不在 /resume 白名单是有意设计
    assert "paused_input" not in _RESUMABLE
