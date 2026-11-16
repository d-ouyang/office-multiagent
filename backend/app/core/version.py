"""应用版本号（v2.3.0-p1.5）。

为什么存在：`frontend/src/version.ts` 原先手写常量，注释写着"与当前已打 tag 对齐，
发新 tag 时改这一处"——实际从 v2.0.0 之后连着两个大版本没人改，侧栏一直显示 v2.0.0。
版本号不能靠人记得改：它应该由**构建产物自带**，前端只负责显示。

来源优先级：
  1. `APP_VERSION` 环境变量——CI 构建时用 `git describe --tags --always` 注入、打进镜像；
  2. 本地 `git describe`——开发机直读仓库（容器里通常没装 git，自动跳过）；
  3. `"dev"`——两者都没有时的诚实兜底，不冒充任何版本。
"""
from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

#: backend/app/core/version.py → parents[3] 即仓库根（本地开发时这里才有 .git）
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: 版本上限长度：`git describe` 在 tag 之后还有提交时会带 `-N-gHASH`，排障要的就是这个尾巴，
#: 但截到 40 字符足够，避免异常输出污染侧栏。
_MAX_LEN = 40


def _git_describe() -> str | None:
    """本地开发兜底：直接问 git。容器里没 git 或超时一律返回 None，绝不阻断启动。"""
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (out.stdout or "").strip()
    return text or None


@lru_cache(maxsize=1)
def app_version() -> str:
    """当前部署的版本号（形如 `v2.3.0`，带提交后缀时为 `v2.3.0-3-gabc1234`）。

    缓存是合理的：版本在一次进程生命周期内不会变（换镜像=换进程）。
    """
    env = (os.environ.get("APP_VERSION") or "").strip()
    if env and env != "dev":
        return env[:_MAX_LEN]
    return (_git_describe() or env or "dev")[:_MAX_LEN]
