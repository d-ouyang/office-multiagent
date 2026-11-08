"""ask_user：HITL 任务中交互澄清（2.1.0 P1-1）。

模型在缺输入（未上传文件、缺关键参数、多方案待选）时调用本工具，
而非"终答里说缺什么然后任务死掉"。调用后：

1. 工具返回 sentinel（`__ask_user__` 标记）——react 循环检测到即终止本轮，
   发 `ask_user` 事件，任务进入 `paused_input`（graph interrupt 落 checkpoint）；
2. 前端弹窗收集用户回答（文本 / 选项 / 上传文件）；
3. `POST /tasks/{id}/answer` 以 `Command(resume=...)` 续跑——已完成步骤
   以"观察回放"形式进上下文，副作用零重跑。

纪律（与全 Agent 共守一致）：ask_user 的 question 必须说清缺什么、
数据从哪来（数据库订单表 / 请上传文件 / 知识库没有），不许干等。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

ASK_SENTINEL_KEY = "__ask_user__"
_MAX_OPTIONS = 6
_MAX_QUESTION = 300
_MAX_FILE_HINT = 120


def make_ask_user_tool() -> Callable[..., dict[str, Any]]:
    """注册进 ToolRegistry 的 ask_user 工具。是否允许暂停由 react 循环层控制
    （allow_ask_user 参数），工具本身永远返回 sentinel——这样 single/multi
    共用同一个白名单条目，multi 下由循环层给出"无法中途确认"的替代观察。"""

    def ask_user(
        question: str = "",
        options: list[str] | None = None,
        need_file: bool = False,
        file_hint: str = "",
        questions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """单问题（question 参数）与多问题（questions 列表，每项
        {question, options?, need_file?, file_hint?}）二选一；统一归一为
        questions 数组——前端弹窗按 n/N 逐题收集后一次性提交。"""
        norm: list[dict[str, Any]] = []
        for item in (questions or []):
            if not isinstance(item, dict):
                continue
            q = str(item.get("question") or "").strip()[:_MAX_QUESTION]
            if not q:
                continue
            norm.append(
                {
                    "question": q,
                    "options": [str(o).strip()[:40] for o in (item.get("options") or []) if str(o).strip()][:_MAX_OPTIONS],
                    "need_file": bool(item.get("need_file")),
                    "file_hint": str(item.get("file_hint") or "").strip()[:_MAX_FILE_HINT],
                }
            )
        if not norm:
            q = str(question or "").strip()[:_MAX_QUESTION]
            if not q:
                return {
                    "error": (
                        "ask_user 必须给出 question（或 questions 列表）：缺什么、数据从哪来"
                        "（数据库订单表 / 请上传文件 / 知识库没有）。空问题无法向用户展示。"
                    )
                }
            opts = [str(o).strip()[:40] for o in (options or []) if str(o).strip()][:_MAX_OPTIONS]
            norm.append(
                {
                    "question": q,
                    "options": opts,
                    "need_file": bool(need_file),
                    "file_hint": str(file_hint or "").strip()[:_MAX_FILE_HINT],
                }
            )
        return {ASK_SENTINEL_KEY: True, "questions": norm[:4]}

    ask_user.__name__ = "ask_user"
    return ask_user
