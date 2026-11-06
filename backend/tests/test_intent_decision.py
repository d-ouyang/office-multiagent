"""混合意图识别：独立句、指代改写、含糊分类和安全回落。"""
import json

from app.core.intent_decision import needs_context_rewrite, resolve_intent
from app.core.llm import LlmError, LlmResult
from app.core.router import decide


def _chat_outputs(*outputs: str):
    queue = list(outputs)

    def call(*_args, **_kwargs):
        content = queue.pop(0)
        return LlmResult(content=content, prompt_tokens=10, completion_tokens=5, total_tokens=15)

    return call


def test_complete_colloquial_question_is_not_rewritten_but_model_classifies():
    resolution = resolve_intent(
        "看看上海卖得怎么样",
        "用户：刚才在聊天气\n助手：晴天",
        chat_fn=_chat_outputs(
            json.dumps(
                {
                    "intents": ["analysis"],
                    "mode": "single",
                    "reason": "询问上海销售表现",
                    "confidence": 0.95,
                },
                ensure_ascii=False,
            )
        ),
    )
    assert resolution.rewritten is False
    assert resolution.route_text == "看看上海卖得怎么样"
    assert resolution.plan.intents == ["analysis"]
    assert resolution.source == "decision_model"
    assert decide(resolution.plan).mode == "single"


def test_anaphora_rewrites_then_classifies():
    resolution = resolve_intent(
        "那上海呢",
        "用户：看看北京卖得怎么样\n助手：北京销售额为……",
        chat_fn=_chat_outputs(
            "看看上海的销售表现怎么样？",
            '{"intents":["analysis"],"mode":"single","reason":"销售分析","confidence":0.9}',
        ),
    )
    assert resolution.rewritten is True
    assert "上海" in resolution.route_text
    assert resolution.plan.intents == ["analysis"]
    assert resolution.tokens_used == 30


def test_anaphora_without_history_does_not_invent_context():
    assert needs_context_rewrite("这个呢", "") is False


def test_bad_rewrite_and_unavailable_classifier_fall_back_to_original_rules():
    calls = iter(
        [
            LlmResult(content="根据公司规定，答案是十天。", total_tokens=12),
            LlmError("down"),
        ]
    )

    def chat(*_args, **_kwargs):
        value = next(calls)
        if isinstance(value, Exception):
            raise value
        return value

    resolution = resolve_intent("这个呢", "用户：年假几天\n助手：……", chat_fn=chat)
    assert resolution.route_text == "这个呢"
    assert resolution.rewrite_failed is True
    assert resolution.source == "rule"


def test_true_cross_capability_task_stays_multi():
    resolution = resolve_intent(
        "先查报销制度，然后基于制度分析上海销售数据",
        "",
        chat_fn=_chat_outputs(
            '{"intents":["rag","analysis"],"mode":"multi","reason":"制度结果交给数据分析","confidence":0.94}'
        ),
    )
    assert decide(resolution.plan).mode == "multi"


def test_decision_model_can_output_orders_intent():
    # p5.5：ALLOWED_INTENTS 加入 orders——决策模型输出的 orders 不被过滤，
    # 路由到 data_analysis（带 query_orders）。零命中问句触发决策模型。
    resolution = resolve_intent(
        "帮我看下最近卖得怎么样",
        "",
        chat_fn=_chat_outputs(
            '{"intents":["orders"],"mode":"single","reason":"查询订单记录","confidence":0.9}'
        ),
    )
    assert resolution.source == "decision_model"
    assert resolution.plan.intents == ["orders"]
    d = decide(resolution.plan)
    assert d.mode == "single"
    assert d.primary_agent == "data_analysis"
