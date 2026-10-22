from app.orchestration.memory import estimate_tokens, prepare_turn


def _round(i: int) -> list[dict[str, str]]:
    return [
        {"role": "user", "content": f"第{i}个问题"},
        {"role": "assistant", "content": f"第{i}个回答"},
    ]


def test_recent_four_rounds_stay_and_older_are_compressed():
    history = []
    for i in range(1, 7):
        history.extend(_round(i))
    text, parts = prepare_turn(history, "继续")
    assert "第5个问题" in parts["recent"]
    assert "第6个问题" in parts["recent"]
    assert "第1个问题" in parts["summary"]
    assert "第2个问题" in parts["summary"]
    assert "第4个问题" not in parts["summary"]
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
