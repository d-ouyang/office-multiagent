"""轻量结果校验器（p6.29）——终答数字对账 observation。

只测纯函数与回调行为（不跑 LLM）；graph 接入层由 test_graph 既有基线覆盖不回归。
"""
import pytest

from app.core.config import settings
from app.orchestration.validator import ValidationReport, validate_final


def test_normalize_commas_and_decimals():
    assert validate_final("合计 32,926 元", ["合计 32926 元"]).ok
    assert validate_final("合计 32,926 元", ["合计 32926.00 元"]).ok


def test_wan_yi_units():
    assert validate_final("卖了 1.2万 单", ["销量 12000"]).ok
    assert validate_final("营收 2.5 亿", ["营收 250000000"]).ok


def test_decimal_trailing_zeros_equal():
    assert validate_final("占比 85.20%", ["占比 85.2%"]).ok


def test_hard_mismatch_flagged():
    rep = validate_final("总额 12,345 元，环比大增", ["总额 32,926 元"])
    assert not rep.ok
    assert rep.unmatched == ["12345"]
    assert rep.checked == 1


def test_small_ints_ignored():
    """小整数到处都是（"3 点建议""第 5 行"），对不上不说明编造——忽略。"""
    rep = validate_final("给你 3 点建议，先看第 5 行", ["共 8 行数据"])
    assert rep.ok


def test_decimal_small_counts_as_hard():
    """带小数就算小也算硬数字（85.2% 这种口径数字容易编）。"""
    rep = validate_final("增长 7.5%", ["增长 2.1%"])
    assert not rep.ok
    assert rep.unmatched == ["7.5"]


def test_task_text_is_valid_source():
    """任务原文里的数字是用户自己给的，终答引用它不算编造。"""
    rep = validate_final("目标 5000 单已完成", ["（观察里没有 5000）"], task="本月目标 5000 单")
    assert rep.ok


def test_no_observations_skipped():
    """一次工具都没调 → 无从对账，主动跳过（模型凭提示词作答合法）。"""
    rep = validate_final("公司大约有 5000 人", [])
    assert rep.skipped and rep.ok


def test_empty_string_final():
    assert validate_final("", ["有数据"]).ok


def test_year_numbers_checked():
    """年份也是 4 位硬数字——写错年份会被标出。"""
    rep = validate_final("2027 年 10 月的数据", ["2026-10-01 至 2026-10-23"])
    assert not rep.ok
    assert "2027" in rep.unmatched
    assert "2026" not in rep.unmatched


def test_settings_switch_off(monkeypatch):
    from app.orchestration.validator import check_and_report

    monkeypatch.setattr(settings, "result_validation", False)
    called = []
    rep = check_and_report(
        final="总额 12345 元",
        observations=["总额 999 元"],
        task="",
        on_mismatch=lambda r: called.append(r),
    )
    assert rep.skipped and not called


def test_check_and_report_calls_back_and_never_raises():
    from app.orchestration.validator import check_and_report

    called = []
    rep = check_and_report(
        final="总额 12,345 元",
        observations=["总额 999 元"],
        task="",
        on_mismatch=lambda r: called.append(r.unmatched),
        label="single:test",
    )
    assert called == [["12345"]]
    assert rep.checked == 1

    # 回调本身炸了也不能外溢
    def boom(_):
        raise RuntimeError("boom")

    rep2 = check_and_report(
        final="总额 12345 元", observations=["总额 999 元"], task="", on_mismatch=boom
    )
    assert not rep2.ok


def test_report_default():
    r = ValidationReport()
    assert r.ok and r.skipped is False
