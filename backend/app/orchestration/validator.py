"""轻量结果校验器（p6.29，设计文档 §十 结果校验器 P1 拍板版）——终答数字对账 observation。

对照 48 页参考架构的差距分析：20 步闭环中第 ⑭ 步「独立结果校验器」缺失。
轻量版 = **不新增 LLM 调用、不阻断、不重跑**：把终答里出现的数字与本次工具
观察（含任务原文）对账，对不上的数字如实标注（事件流 + WARNING 日志），
把"数字是不是编的"的最终判断留给用户。

只校验「硬数字」，压误报：
  · 整数部分 ≥4 位（1000+，如总额 32,926）或带小数（如 85.2%）→ 参与；
  · 小整数（"3 点建议""第 5 行"）到处都是，对不上也不说明编造 → 忽略；
  · 任务原文里出现的数字是用户自己给的，合法来源 → 计入来源池；
  · 一次工具都没调过的终答 = 模型凭提示词作答，无从对账 → 跳过。

数字归一化：千分位逗号、万/亿量词、小数尾零（"1.20 万" == "12000"）。
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

#: 千分位写法（12,345.6）或普通写法（12345.6），可带 万/亿 量词（允许中间有空格）
_NUM_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*([万亿])?")


def _normalize(text: str) -> set[str]:
    """抽数字并归一化成可比字符串；只保留「硬数字」。"""
    out: set[str] = set()
    for m in _NUM_RE.finditer(text or ""):
        raw, unit = m.group(1), m.group(2)
        plain = raw.replace(",", "")
        if "." in plain:
            plain = plain.rstrip("0").rstrip(".")
        if unit == "万":
            value = float(plain) * 10000
        elif unit == "亿":
            value = float(plain) * 100000000
        else:
            value = float(plain)
        # 硬数字：整数部分 ≥4 位，或带小数。整数去 .0、小数保留足够精度，统一可比
        # （不用 %g：它只保 6 位有效数字，7 位数会被写成 1.23457e+06 破坏对账）
        if value >= 1000 or "." in raw:
            if value == int(value):
                out.add(str(int(value)))
            else:
                out.add(f"{value:.10f}".rstrip("0").rstrip("."))
    return out


@dataclass
class ValidationReport:
    checked: int = 0                    # 终答里参与对账的硬数字个数
    unmatched: list[str] = field(default_factory=list)  # 来源池里对不上的
    skipped: bool = False               # 无工具观察 → 无从对账，主动跳过

    @property
    def ok(self) -> bool:
        return not self.unmatched


def validate_final(
    final: str,
    observations: list[str],
    *,
    task: str = "",
) -> ValidationReport:
    """终答数字 vs 观察数字对账。观察为空（没调过工具）→ skipped。"""
    obs_texts = [o for o in observations if o]
    if not obs_texts:
        return ValidationReport(skipped=True)
    source = _normalize(" ".join(obs_texts)) | _normalize(task)
    nums = _normalize(final)
    return ValidationReport(
        checked=len(nums),
        unmatched=sorted(n for n in nums if n not in source),
    )


def check_and_report(
    *,
    final: str,
    observations: list[str],
    task: str,
    on_mismatch: Callable[[ValidationReport], None] | None = None,
    label: str = "result_validator",
) -> ValidationReport:
    """跑校验；对不上时 log WARNING 并回调 on_mismatch(report)（由调用方决定事件形态）。

    任何异常都吞掉（校验器坏了不能影响任务本身）——"不阻断"优先于"必校验"。
    """
    from ..core.config import settings

    if not getattr(settings, "result_validation", True):
        return ValidationReport(skipped=True)
    try:
        report = validate_final(final, observations, task=task)
    except Exception:  # noqa: BLE001 - 校验器自身故障不外溢
        logger.exception("结果校验器异常（忽略）")
        return ValidationReport(skipped=True)
    if report.unmatched:
        logger.warning(
            "结果校验[%s]：终答数字未在观察/任务原文中出现 → %s", label, report.unmatched
        )
        if on_mismatch is not None:
            try:
                on_mismatch(report)
            except Exception:  # noqa: BLE001
                logger.exception("结果校验回调失败（忽略）")
    return report
