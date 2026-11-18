#!/usr/bin/env python3
"""评测 CLI（v2.2.0-p1.12 / Phase E2）——对 golden set 批跑并输出通过率。

用法（backend/ 目录）：
  .venv/bin/python scripts/run_evals.py                    # 连真实环境库跑全部用例
  .venv/bin/python scripts/run_evals.py --filter gs-00     # 只跑前缀匹配的用例
  .venv/bin/python scripts/run_evals.py --case gs-001      # 单条

模式说明：
  · 缺省（本 CLI）= 真实环境库 + EvalAdapter（工具真执行，LLM 决策走规则回落）——
    用于改 Prompt/路由后的校准与抽样；
  · CI 门禁 = pytest tests/test_golden_set.py（sqlite 环境，同断言集）。
退出码：全部通过 0，有失败 1（可挂 CI / git hook）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/ 入 path

from evals.eval_core import load_cases, run_case  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="golden set 评测")
    ap.add_argument("--filter", default="", help="按 id 前缀过滤")
    ap.add_argument("--case", default="", help="只跑指定 id")
    args = ap.parse_args()

    cases = load_cases(prefix=args.filter or None)
    if args.case:
        cases = [c for c in cases if c.get("id") == args.case]
    if not cases:
        print("没有匹配的用例")
        return 2

    print(f"{'用例':<38} {'route':<7} {'tools':<30} 结果")
    print("-" * 92)
    failed = 0
    for case in cases:
        res = run_case(case)  # engine=None → 真实环境库
        mark = "✅ PASS" if res.ok else "❌ FAIL"
        if not res.ok:
            failed += 1
        print(f"{res.case_id:<38} {res.route:<7} {','.join(res.tools_called):<30} {mark}")
        for f in res.failures:
            print(f"{'':<38}   └ {f}")
    print("-" * 92)
    print(f"{len(cases) - failed}/{len(cases)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
