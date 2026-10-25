"""Skill 注册表（P1）——docs/项目架构调整-引入Skill层-2026-10-24.md。

P1 只打通三条链路，**不接入运行时路由（P2 才做）**：
  1. 加载：扫描 skills/<name>/ 下的 spec.yaml + prompt.md
  2. 指令：暴露该 skill 的 system prompt（供注入）
  3. 约束：从全量 ToolRegistry 裁剪出该 skill 声明的工具子集

纪律与 orchestration/agents.py 保持一致：
  · 未注册的 skill 回落 None（不猜、不编）。
  · spec 里声明了未注册工具 → 记 warning 并跳过（对该 skill 能力缺失）。
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from ..core.config import settings
from ..orchestration.tools import ToolRegistry
from .base import SkillSpec, parse_skill

logger = logging.getLogger(__name__)

SPEC_FILE = "spec.yaml"
PROMPT_FILE = "prompt.md"


def _resolve_skills_dir() -> Path:
    """定位 skills 目录：显式配置优先，其次容器路径，最后本地本目录。"""
    if settings.skills_dir:
        p = Path(settings.skills_dir)
        if p.exists():
            return p
    candidates = [
        Path("/app/app/skills"),  # 容器内：backend 根为 /app
        Path(__file__).resolve().parent,  # 本地：app/skills 本目录
    ]
    for c in candidates:
        if c.is_dir():
            return c
    raise FileNotFoundError("skills 目录未找到（设 SKILLS_DIR 或放 backend/app/skills）")


def load_skill_specs() -> dict[str, SkillSpec]:
    """扫描 skills 目录，每个含 spec.yaml 的子目录即一个 skill。

    坏 spec 不炸整个注册表：单个解析失败只跳过它并记 warning（fail-closed 的子集表现）。
    """
    root = _resolve_skills_dir()
    specs: dict[str, SkillSpec] = {}
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith((".", "_")):
            continue
        spec_file = child / SPEC_FILE
        if not spec_file.exists():
            logger.debug("跳过 %s：没有 %s", child.name, SPEC_FILE)
            continue
        try:
            raw = yaml.safe_load(spec_file.read_text(encoding="utf-8")) or {}
        except Exception as e:  # noqa: BLE001 - 单个 spec 坏不能拖垮整表
            logger.warning("skill %s 的 %s 解析失败，跳过：%s", child.name, SPEC_FILE, e)
            continue
        if not isinstance(raw, dict):
            logger.warning("skill %s 的 %s 不是映射，跳过", child.name, SPEC_FILE)
            continue
        prompt_file = child / PROMPT_FILE
        prompt = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else ""
        spec = parse_skill(raw, default_name=child.name, prompt=prompt)
        if not spec.name:
            logger.warning("skill %s 缺少 name，跳过", child.name)
            continue
        specs[spec.name] = spec
    return specs


class SkillRegistry:
    """skill 查询与工具裁剪。只读视图，不负责执行。"""

    def __init__(self, specs: dict[str, SkillSpec] | None = None) -> None:
        self._skills: dict[str, SkillSpec] = dict(specs or {})

    # ---- 查询 ----
    def names(self, *, enabled_only: bool = False) -> list[str]:
        return sorted(n for n, s in self._skills.items() if (s.enabled or not enabled_only))

    def get(self, name: str | None) -> SkillSpec | None:
        return self._skills.get((name or "").strip())

    def describe(self) -> list[dict[str, str]]:
        """清单（调试/管理端用）。"""
        return [
            {
                "name": s.name,
                "title": s.title,
                "description": s.description,
                "enabled": str(s.enabled),
            }
            for s in (self._skills[n] for n in sorted(self._skills))
        ]

    def prompt_for(self, name: str | None) -> str:
        """取该 skill 的指令正文；未注册返回空串（调用方按无附加指令处理）。"""
        spec = self.get(name)
        return (spec.prompt if spec else "") or ""

    def match(
        self,
        text: str = "",
        intent: str | None = None,
        *,
        enabled_only: bool = True,
    ) -> SkillSpec | None:
        """按触发条件匹配 skill；无命中返回 None（调用方回落 general）。"""
        for n in sorted(self._skills):  # 排序保证结果稳定
            s = self._skills[n]
            if enabled_only and not s.enabled:
                continue
            if s.matches(text, intent):
                return s
        return None

    # ---- 工具约束 ----
    def restrict_tools(self, base: ToolRegistry, spec: SkillSpec) -> ToolRegistry:
        """按 skill 声明的工具白名单裁剪；未注册的工具跳过（对该 skill 不可见）。"""
        reg = ToolRegistry()
        for name in spec.tools:
            if not base.has(name):
                logger.warning(
                    "skill %s 声明了未注册工具 %s（跳过=对该 skill 能力缺失）", spec.name, name
                )
                continue
            desc = next((d["description"] for d in base.describe() if d["name"] == name), "")
            reg.register(name, base._tools[name], desc)  # noqa: SLF001 - 同包内装配
        return reg


def load_skill_registry() -> SkillRegistry:
    """从磁盘加载一次（不缓存：与 agents.yaml 一致，改完重启即生效）。"""
    return SkillRegistry(load_skill_specs())
