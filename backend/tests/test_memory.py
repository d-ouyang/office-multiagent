from app.orchestration.memory import estimate_tokens, prepare_turn


def _round(i: int) -> list[dict[str, str]]:
    return [
        {"role": "user", "content": f"第{i}个问题"},
        {"role": "assistant", "content": f"第{i}个回答"},
    ]


def test_recent_eight_rounds_stay_and_older_are_summarized():
    """v2.4.2：默认保留 8 轮原文（旧值 4 轮 + 每轮 80 字切片，第二轮就丢上文）。"""
    history = []
    for i in range(1, 11):
        history.extend(_round(i))
    text, parts = prepare_turn(history, "继续")
    assert "第9个问题" in parts["recent"]
    assert "第10个问题" in parts["recent"]
    assert "第1个问题" in parts["summary"]
    assert "第2个问题" in parts["summary"]
    assert "第3个问题" not in parts["summary"]   # 第 3~10 轮都在近期原文里
    assert "第1个问题" not in parts["recent"]
    assert "【历史摘要】" in text
    assert "【本轮问题】" in text


def test_pronoun_asks_to_resolve_from_history():
    history = _round(1)
    text, parts = prepare_turn(history, "把这个再算一遍")
    assert "coref" in parts
    assert "指代" in text


def test_no_history_is_just_the_question():
    text, parts = prepare_turn([], "上海一月实付")
    assert parts["current"] == "上海一月实付"
    assert "summary" not in parts
    assert "coref" not in parts
    assert estimate_tokens("上海") == 2
