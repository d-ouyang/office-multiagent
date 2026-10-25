"""Skill 能力包的基础契约（P1）——docs/项目架构调整-引入Skill层-2026-10-24.md。

三层边界（别混）：
  · Tool   原子函数（db_query / write_document …），由 ToolRegistry 装配，无业务语义。
  · Skill  可复用能力包 = 声明(spec.yaml) + 指令(prompt.md) + 可选编排(run.py)。
  · Agent  运行时实体，被指派一组 skill，负责调度执行（single ReAct / multi DAG）。

纪律：
  · **fail-closed**：enabled 缺省 False；未启用或未注册的 skill 一律回落，不猜、不编。
  · skill 只"声明"工具名，不持有工具实现；运行时由 SkillRegistry 裁剪出受限工具集。
  · 多 skill 并发时各自独立加载，run.py 不得持有跨任务的全局可变状态。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 避免 skills ↔ orchestration 循环导入
    from ..orchestration.tools import ToolRegistry

logger = logging.getLogger(__name__)

FALLBACK_SKILL = "general"


@dataclass(frozen=True)
class Trigger:
    """触发条件：intent 与 planner 的意图名对齐，keywords 为关键词兜底。"""

    intent: str = ""
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemoryAccess:
    """该 skill 可访问的记忆范围；缺省全关（最小权限）。"""

    session_read: bool = False
    user_longterm: bool = False
    semantic_search: bool = False


@dataclass(frozen=True)
class SkillSpec:
    """一个 skill 的完整声明。由 spec.yaml 解析而来，指令正文放 prompt。"""

    name: str
    title: str = ""
    description: str = ""
    tools: tuple[str, ...] = ()
    triggers: tuple[Trigger, ...] = ()
    model_preference: str | None = None
    memory: MemoryAccess = MemoryAccess()
    fallback: str = FALLBACK_SKILL
    enabled: bool = False  # fail-closed：不显式打开即不可被路由
    prompt: str = ""  # prompt.md 正文（指令）

    def has_tool(self, name: str) -> bool:
        return name in self.tools

    def matches(self, text: str = "", intent: str | None = None) -> bool:
        """命中判定：显式 intent 优先，其次关键词包含匹配。空输入一律不命中。"""
        if intent:
            for t in self.triggers:
                if t.intent and t.intent == intent:
                    return True
        low = (text or "").lower()
        if not low:
            return False
        for t in self.triggers:
            for kw in t.keywords:
                if kw and kw.lower() in low:
                    return True
        return False


@dataclass
class SkillContext:
    """skill 执行上下文：只给它受限工具集 + 必要的身份/落库信息。"""

    tools: "ToolRegistry | None" = None
    engine: Any = None
    username: str | None = None
    user_id: int | None = None
    task_id: str | None = None


def _as_trigger(item: Any) -> Trigger | None:
    """触发项兼容两种写法：纯字符串（当关键词）或 {intent, keywords} 映射。"""
    if isinstance(item, str):
        return Trigger(keywords=(item,)) if item.strip() else None
    if isinstance(item, dict):
        intent = str(item.get("intent") or "").strip()
        raw_kws = item.get("keywords") or []
        if isinstance(raw_kws, str):
            raw_kws = [raw_kws]
        kws = tuple(str(k) for k in raw_kws if str(k).strip())
        if not intent and not kws:
            return None
        return Trigger(intent=intent, keywords=kws)
    return None


def parse_skill(raw: Any, *, default_name: str = "", prompt: str = "") -> SkillSpec:
    """把 spec.yaml 的原始映射解析成 SkillSpec。缺字段走保守默认，不抛异常。"""
    data = raw if isinstance(raw, dict) else {}
    name = str(data.get("name") or default_name or "").strip()
    mem_raw = data.get("memory") if isinstance(data.get("memory"), dict) else {}
    pref = data.get("model_preference")
    return SkillSpec(
        name=name,
        title=str(data.get("title") or name),
        description=str(data.get("description") or "").strip(),
        tools=tuple(str(t) for t in (data.get("tools") or [])),
        triggers=tuple(
            t for t in (_as_trigger(i) for i in (data.get("triggers") or [])) if t is not None
        ),
        model_preference=str(pref).strip() if pref else None,
        memory=MemoryAccess(
            session_read=bool(mem_raw.get("session_read", False)),
            user_longterm=bool(mem_raw.get("user_longterm", False)),
            semantic_search=bool(mem_raw.get("semantic_search", False)),
        ),
        fallback=str(data.get("fallback") or FALLBACK_SKILL).strip(),
        enabled=bool(data.get("enabled", False)),  # 缺省关闭
        prompt=(prompt or "").strip(),
    )
