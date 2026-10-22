"""db_query 只读工具（p5.1a）——真实 SQL 查询，带硬护栏。

护栏（fail-closed，全部有测试断言）：
  1. 仅允许单条 SELECT / WITH（CTE 只读）开头。
  2. 禁止分号（防多语句夹带写操作）。
  3. 词边界拦截写关键字（INSERT/UPDATE/DELETE/DROP/…）——用 \\b 边界，
     不会误杀 `created_at` / `update_time` 这类列名。
  4. 强制 LIMIT：没有就自动补 `LIMIT max_rows`，并硬截断返回行数。
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|call|attach|pragma|detach)\b",
    re.IGNORECASE,
)


_PREDICATE = re.compile(r"\b(where|group\s+by|having)\b|\b(count|sum|avg|min|max)\s*\(", re.IGNORECASE)
_LIMIT_TAIL = re.compile(r"\blimit\s+(\d+)\s*$", re.IGNORECASE)


def check_readonly(sql: str, *, max_rows: int = 50) -> str:
    """护栏：通过则返回规范化后的 SQL；违规抛 ValueError（工具层转结构化错误如实告知）。"""
    s = (sql or "").strip().rstrip(";").strip()
    if not s:
        raise ValueError("SQL 为空")
    if ";" in s:
        raise ValueError("只允许单条语句（检测到分号）")
    first = s.split(None, 1)[0].lower()
    if first not in ("select", "with"):
        raise ValueError("只允许 SELECT 查询")
    hit = _FORBIDDEN.search(s)
    if hit:
        raise ValueError(f"只读查询中禁止出现 {hit.group(1).upper()}")
    if not _PREDICATE.search(s):
        raise ValueError("查询必须带 WHERE、GROUP BY 或聚合函数，避免整表读取")
    limited = _LIMIT_TAIL.search(s)
    if not limited:
        s = f"{s} LIMIT {int(max_rows)}"
    elif int(limited.group(1)) > max_rows:
        s = s[: limited.start()] + f"LIMIT {int(max_rows)}"
    if s.lower().startswith("select"):
        s = "SELECT /*+ MAX_EXECUTION_TIME(3000) */" + s[6:]
    return s


def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime | date | Decimal):
        return str(v)
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    try:
        json.dumps(v)
        return v
    except (TypeError, ValueError):
        return str(v)


def make_db_query_tool(engine: Engine | None, *, max_rows: int = 50) -> Callable[..., Any]:
    """构造 db_query 工具函数。engine 为 None 时调用即报"数据库不可用"（不假装）。"""

    def db_query(sql: str) -> dict[str, Any]:
        if engine is None:
            raise RuntimeError("数据库不可用：未配置数据库连接")
        checked = check_readonly(sql, max_rows=max_rows)
        with engine.connect() as conn:
            result = conn.execute(text(checked))
            columns = list(result.keys())
            rows = result.mappings().all()
        data = [{k: _jsonable(v) for k, v in dict(r).items()} for r in rows[:max_rows]]
        return {
            "columns": columns,
            "rows": data,
            "row_count": len(data),
            "sql": checked,
        }

    db_query.__name__ = "db_query"
    return db_query
