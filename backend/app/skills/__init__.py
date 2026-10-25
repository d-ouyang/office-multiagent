"""Skill 能力层（P1）——介于 Tool（原子函数）与 Agent（运行时实体）之间的可复用能力包。

详见 docs/项目架构调整-引入Skill层-2026-10-24.md。

P1 范围：仅加载 + 受限工具集，**不接入 router**（那是 P2）。新增本模块不改动任何运行时代码路径。
"""
from .base import MemoryAccess, SkillContext, SkillSpec, Trigger
from .registry import SkillRegistry, load_skill_registry

__all__ = [
    "MemoryAccess",
    "SkillContext",
    "SkillRegistry",
    "SkillSpec",
    "Trigger",
    "load_skill_registry",
]
