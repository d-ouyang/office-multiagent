"""会话摘要测试（v2.4.2）。

事故背景：旧实现用 `answer[:80]` 切片当摘要，730 字的回答被砍成 "- 时…"，
结尾「需要我导出成文档吗」丢失 → 用户回「需要」时模型判成闲聊、反问"需要什么"。
本文件锁住三件事：**关键信息不丢、数字不改写、问句必须留下**。
"""
from app.orchestration.memory import prepare_turn
from app.orchestration.summary import (
    extract_open_questions,
    merge_summaries,
    render_summary,
    summarize_round,
)

ANSWER = """热力图已生成（城市×月份，指标为实付金额）。
**口径**：下单时间 2026-09-17 至 2026-11-17，按「月份×城市」分组，共 66 个组合。
**要点**：
- 上海是绝对主力：10 月 30,581 元、11 月 18,830 元，远超其他城市。
- 安庆 11 月 5,136 元，是少数反超 10 月的城市。
文件已保存为 分析报告.docx。
需要我把这份热力图+分析导出成文档吗？"""


def test_rule_summary_keeps_numbers_verbatim():
    """S-1：数字原样保留（不许取整/改写）。"""
    payload = summarize_round(1, "画热力图", ANSWER)
    joined = " ".join(payload["numbers"])
    assert "30,581" in joined and "18,830" in joined


def test_rule_summary_keeps_open_question():
    """S-2：结尾的问句必须留在摘要里——它是下一轮指代对齐的锚点。"""
    payload = summarize_round(1, "画热力图", ANSWER)
    assert payload["open_questions"]
    assert "导出成文档吗" in payload["open_questions"][-1]


def test_rule_summary_extracts_only_real_filenames():
    """S-3：产物只认已知扩展名——金额 "18,830.18" 不能被当成文件名。"""
    payload = summarize_round(1, "画热力图", ANSWER)
    assert payload["artifacts"] == ["分析报告.docx"]


def test_rule_summary_conclusions_prefer_numbered_lines():
    """S-4：结论优先取带结论词/数字的句子。"""
    payload = summarize_round(1, "画热力图", ANSWER)
    text = " ".join(payload["conclusions"])
    assert "上海" in text


def test_short_confirmation_question_is_kept_as_intent():
    """S-5：两个字的追问（「需要」）本身也要进摘要——它是最关键的上下文线索。"""
    payload = summarize_round(2, "需要", "好的，这就导出。")
    assert payload["user_intent"] == "需要"


def test_merge_prefers_rule_for_facts_and_llm_for_narrative():
    """S-6：合并时数字/问句以规则为准，意图/结论用模型归纳。"""
    rule = summarize_round(1, "画热力图", ANSWER)
    llm = {
        "turn": 1,
        "user_intent": "用户要看两月城市热力图",
        "conclusions": ["上海居首（模型改写版）"],
        "numbers": ["3万"],          # 模型把数字改写了
        "artifacts": [],
        "open_questions": [],        # 模型把问句吞了
    }
    merged = merge_summaries(rule, llm)
    assert merged["user_intent"].startswith("用户要看两月")
    assert merged["conclusions"] == ["上海居首（模型改写版）"]
    assert "30,581" in " ".join(merged["numbers"])     # 数字用规则版
    assert merged["open_questions"]                         # 问句用规则版


def test_render_summary_is_compact():
    """S-7：长回答渲染后明显短于原文（用 1200 字的回答测压缩比）。"""
    body, question = ANSWER.rsplit("需要我", 1)
    long_answer = body + ("补充说明：这一段的细节在下结论时并不需要。\n" * 30) + "需要我" + question
    payload = summarize_round(1, "画热力图", long_answer)
    text = render_summary(payload, max_chars=400)
    assert len(text) < len(long_answer) / 2
    assert "[第1轮]" in text
    assert "待确认" in text


def test_prepare_turn_injects_pending_question():
    """S-8：上一轮有悬着的提问时，直接告诉模型「用户可能在回答它」。"""
    history = [
        {"role": "user", "content": "画热力图"},
        {"role": "assistant", "content": ANSWER},
    ]
    text, parts = prepare_turn(history, "需要")
    assert "coref" in parts
    assert "导出成文档吗" in text
    assert "不要反问" in text


def test_prepare_turn_keeps_recent_full_text():
    """S-9：近期轮次是原文，不能被截断（旧值是 80 字）。"""
    long_answer = "很长的回答。" * 200  # 1200 字
    history = [{"role": "user", "content": "问题"}, {"role": "assistant", "content": long_answer}]
    _, parts = prepare_turn(history, "继续")
    assert len(parts["recent"]) >= len(long_answer)


def test_extract_open_questions_ignores_mid_text_rhetoric():
    """S-10：只取末尾的提问，中间的设问不算。"""
    answer = "为什么要这样？因为数据不全。以上是分析结论。需要我导出吗？"
    qs = extract_open_questions(answer)
    assert "导出" in qs[-1]          # 最后一个才是真正待回答的
    assert all("为什么" not in q for q in qs[-1:])
