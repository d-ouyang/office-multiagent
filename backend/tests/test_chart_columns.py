"""render_chart 列名解析测试（v2.4.1）。

真跑事故（2026-11-17）：第一张引导卡「多维图表」调用
  render_chart(clean_id=..., x=month, series=city, y=metric_value)
报「数值列不存在：metric_value。现有列：city、month、order_count、m_sum_pay」。

根因：query_orders 的指标列名随分组列数变化——单列分组产 `metric_value`，
多列分组产 `m_sum_pay`；而 agents.yaml 的提示词只写了前者，模型照抄。
修法：解析别名 + 报错带正确写法提示，两道一起上。
"""
import pytest

from app.orchestration.tools_chart import _require, _resolve_column

#: 多列分组（group_by=month,city,metric=sum_pay）的真实表头
MULTI = ["month", "city", "order_count", "m_sum_pay"]


def test_metric_value_alias_resolves_to_m_column():
    """C-1：多列分组下 metric_value 别名 → 唯一的 m_* 列。"""
    assert _resolve_column("metric_value", MULTI) == "m_sum_pay"


def test_prefix_toggle_both_directions():
    """C-2：带/不带 m_ 前缀互相能对上。"""
    assert _resolve_column("sum_pay", MULTI) == "m_sum_pay"
    assert _resolve_column("m_sum_pay", ["grp", "order_count", "sum_pay"]) == "sum_pay"


def test_ambiguous_alias_not_guessed():
    """C-3：有多个 m_* 列时不猜——猜错比报错更糟（用户拿到的是错的图）。"""
    headers = ["month", "city", "order_count", "m_sum_pay", "m_order_count"]
    assert _resolve_column("metric_value", headers) == "metric_value"


def test_real_column_untouched():
    """C-4：本来就对的列名不能被改写。"""
    assert _resolve_column("city", MULTI) == "city"
    assert _resolve_column("order_count", MULTI) == "order_count"


def test_error_message_hints_correct_column_name():
    """C-5：真解析不了时，报错要直接告诉模型正确写法。"""
    with pytest.raises(ValueError) as ei:
        _require(MULTI, "metric_value", "数值列")
    message = str(ei.value)
    assert "m_sum_pay" in message
    assert "m_ 前缀" in message
