"""brain.extract_json 容错测试（v2.4.1）。

真跑见证（2026-11-17 多维图表卡片）：同一条任务 3 次里有 1 次死于
「模型输出无法解析为决策 JSON」——模型其实给出了完整决策，只是格式上多了个尾逗号
或字符串里带了裸换行。严格 json.loads 一失败就整条终止，代价太大。
"""
from app.orchestration.brain import extract_json


def test_plain_json():
    assert extract_json('{"action": "query_orders", "action_input": {}}') == {
        "action": "query_orders",
        "action_input": {},
    }


def test_json_with_suffix_text():
    """JSON 前后带说明文字：取配平的那个对象。"""
    raw = '好的，我来查：{"action": "query_orders", "action_input": {"city": "上海"}} 以上。'
    assert extract_json(raw)["action"] == "query_orders"


def test_trailing_comma():
    """末项多一个逗号（模型高频错误）。"""
    assert extract_json('{"a": 1, "b": 2,}') == {"a": 1, "b": 2}
    assert extract_json('{"a": [1, 2,]}') == {"a": [1, 2]}


def test_raw_newline_inside_string():
    """字符串里带裸换行：strict=False 允许控制字符。"""
    raw = '{"thought": "第一行\n第二行", "action": "query_orders"}'
    assert extract_json(raw)["action"] == "query_orders"


def test_code_block_with_nested_object():
    raw = '```json\n{"a": {"b": [1, 2]}}\n```'
    assert extract_json(raw) == {"a": {"b": [1, 2]}}


def test_two_objects_takes_the_first():
    """模型给"决策 + 示例"两个对象时取第一个，不能黏在一起。"""
    raw = '{"a": 1}\n示例：{"b": 2}'
    assert extract_json(raw) == {"a": 1}


def test_invalid_returns_none():
    assert extract_json("{这不是 JSON") is None
    assert extract_json("") is None
    assert extract_json("完全没有花括号") is None
