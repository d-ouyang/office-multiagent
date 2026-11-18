#!/usr/bin/env python3
"""CI 检查（v2.2.0-p1.4 / B1 判据）：模型调用必须收口到网关，绕过即失败。

两条红线（对 backend/app/ 全量扫描）：
  1. 禁止裸 provider SDK import——openai / anthropic / litellm 等 SDK 一旦出现在
     业务代码，就等于网关之外的暗门；
  2. 禁止业务代码直连已知 provider 域名——所有 LLM 网络调用必须经 core/llm.py
     （它从 models.yaml 读 base_url，配置指向 gateway）。
白名单：core/llm.py（唯一合法的出站点）、本脚本自身。

退出码：0=通过；1=发现违规（CI 步骤失败，阻止部署）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

BANNED_SDKS = re.compile(
    r"^\s*(import\s+(openai|anthropic|litellm|cohere|mistralai)|from\s+(openai|anthropic|litellm|cohere|mistralai)\s)",
)
BANNED_HOSTS = re.compile(r"(api\.deepseek\.com|api\.siliconflow\.cn|api\.openai\.com|open\.anthropic\.com)")
ALLOWLIST = {"llm.py"}


def check() -> list[str]:
    violations: list[str] = []
    for py in sorted(APP.rglob("*.py")):
        rel = py.relative_to(APP).as_posix()
        if rel in ALLOWLIST or "__pycache__" in rel:
            continue
        text = py.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if BANNED_SDKS.search(line):
                violations.append(f"{rel}:{i} 裸 provider SDK import（须走 core/llm.py）: {line.strip()[:90]}")
            if BANNED_HOSTS.search(line):
                violations.append(f"{rel}:{i} 直连 provider 域名（须走 core/llm.py 经网关）: {line.strip()[:90]}")
    return violations


def main() -> int:
    violations = check()
    if violations:
        print(f"❌ 发现 {len(violations)} 处绕过 LLM 网关的调用：")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("✅ LLM 收口检查通过：无裸 SDK import、无直连 provider 域名")
    return 0


if __name__ == "__main__":
    sys.exit(main())
