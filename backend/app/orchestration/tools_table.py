"""上传表格的清洗与分析。

清洗不改原文件，另存一份表。分析只接受这份表的 clean_id，不直接读原始上传。
缺失值不填补，异常值不删除；关键列为空的行会从清洗结果中剔除，并在报告里计数。
"""
from __future__ import annotations

import csv
import json
import re
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .tools_doc import check_inside_base, load_table_grid, normalize_doc_name

_CLEAN_ID = re.compile(r"^c-[0-9a-f]{16}$")
_NULL_TOKENS = {"null", "none", "n/a", "na", "nan", "-", "—", "无", "空", "nil"}
_AGGS = {"count", "sum", "mean", "min", "max", "count_distinct"}
_OPS = {"eq", "ne", "contains", "gt", "gte", "lt", "lte"}
_PREVIEW = 5
_MAX_GROUPS = 100


def _as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [value]


def _blank_to_empty(text: str) -> str:
    cleaned = text.replace("\u3000", " ").strip()
    if cleaned.casefold() in _NULL_TOKENS:
        return ""
    return cleaned


def _parse_number(text: str) -> float | None:
    raw = text.replace(",", "").replace("，", "").replace("￥", "").replace("¥", "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _unique_headers(headers: list[str]) -> tuple[list[str], list[dict[str, str]]]:
    seen: dict[str, int] = {}
    out: list[str] = []
    renames: list[dict[str, str]] = []
    for index, header in enumerate(headers, 1):
        name = header.replace("\u3000", " ").strip() or f"列{index}"
        if name != header:
            renames.append({"from": header, "to": name})
        count = seen.get(name, 0) + 1
        seen[name] = count
        if count > 1:
            renamed = f"{name}_{count}"
            renames.append({"from": name, "to": renamed})
            name = renamed
        out.append(name)
    return out, renames


def _align(row: list[str], width: int) -> list[str]:
    cells = row[:width]
    if len(cells) < width:
        cells.extend([""] * (width - len(cells)))
    return cells


def clean_grid(
    headers: list[str],
    rows: list[list[str]],
    key_columns: list[str],
) -> dict[str, Any]:
    named, renames = _unique_headers([_blank_to_empty(h) for h in headers])
    width = len(named)
    normalized = [_align([_blank_to_empty(c) for c in row], width) for row in rows]
    rows_in = len(normalized)

    key_set = set(key_columns)
    keep_idx = [i for i in range(width) if any(row[i] for row in normalized) or named[i] in key_set]
    dropped_columns = [named[i] for i in range(width) if i not in keep_idx]
    if keep_idx and len(keep_idx) != width:
        named = [named[i] for i in keep_idx]
        normalized = [[row[i] for i in keep_idx] for row in normalized]
        width = len(named)
    if not named:
        raise ValueError("表格没有可用的列")

    missing_keys = [name for name in key_columns if name not in named]
    if missing_keys:
        raise ValueError(f"没有这些关键列：{'、'.join(missing_keys)}。现有列：{'、'.join(named)}")

    empty_rows = 0
    repeated_header = 0
    kept: list[list[str]] = []
    header_tuple = tuple(named)
    for row in normalized:
        if not any(row):
            empty_rows += 1
            continue
        if tuple(row) == header_tuple:
            repeated_header += 1
            continue
        kept.append(row)

    seen_rows: set[tuple[str, ...]] = set()
    unique: list[list[str]] = []
    duplicate_rows = 0
    for row in kept:
        key = tuple(row)
        if key in seen_rows:
            duplicate_rows += 1
            continue
        seen_rows.add(key)
        unique.append(row)

    key_indexes = [named.index(name) for name in key_columns]
    missing_key_rows = 0
    ready: list[list[str]] = []
    for row in unique:
        if key_indexes and any(not row[i] for i in key_indexes):
            missing_key_rows += 1
            continue
        ready.append(row)

    column_missing = []
    numeric_issues = []
    total = len(ready)
    for index, name in enumerate(named):
        values = [row[index] for row in ready]
        missing = sum(1 for value in values if not value)
        column_missing.append(
            {"column": name, "missing": missing, "rows": total, "missing_rate": round(missing / total, 4) if total else 0}
        )
        parsed = 0
        bad = 0
        for value in values:
            if not value:
                continue
            if _parse_number(value) is None:
                bad += 1
            else:
                parsed += 1
        if parsed and bad:
            numeric_issues.append({"column": name, "parsed": parsed, "unparsed": bad})

    return {
        "columns": named,
        "rows": ready,
        "rows_in": rows_in,
        "rows_out": len(ready),
        "dropped_empty_rows": empty_rows,
        "dropped_duplicate_rows": duplicate_rows,
        "dropped_repeated_header": repeated_header,
        "dropped_empty_columns": dropped_columns,
        "header_renames": renames,
        "key_columns": key_columns,
        "missing_key_rows": missing_key_rows,
        "column_missing": column_missing,
        "numeric_issues": numeric_issues,
    }


def _write_clean(base: Path, columns: list[str], rows: list[list[str]], meta: dict[str, Any]) -> str:
    clean_id = "c-" + secrets.token_hex(8)
    folder = base / "_clean"
    folder.mkdir(parents=True, exist_ok=True)
    target = (folder / f"{clean_id}.csv").resolve()
    if not target.is_relative_to(folder.resolve()):
        raise ValueError("非法清洗结果路径")
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)
    (folder / f"{clean_id}.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    return clean_id


def _load_clean(base: Path, clean_id: str) -> tuple[list[str], list[list[str]], dict[str, Any]]:
    if not _CLEAN_ID.match(clean_id or ""):
        raise ValueError("clean_id 无效。请先调用 clean_table，不要把原始文件名传进来。")
    folder = (base / "_clean").resolve()
    csv_path = (folder / f"{clean_id}.csv").resolve()
    meta_path = folder / f"{clean_id}.json"
    if not csv_path.is_relative_to(folder) or not csv_path.is_file():
        raise FileNotFoundError(f"找不到清洗结果：{clean_id}")
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        grid = list(csv.reader(handle))
    if not grid:
        raise ValueError("清洗结果是空的")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    return grid[0], grid[1:], meta


def _match_filter(row: dict[str, str], item: dict[str, Any]) -> bool:
    column = str(item.get("column") or "")
    op = str(item.get("op") or "")
    expected = str(item.get("value") if item.get("value") is not None else "")
    if column not in row:
        raise ValueError(f"过滤列不存在：{column}")
    if op not in _OPS:
        raise ValueError(f"不支持的过滤方式：{op}（可用 {'/'.join(sorted(_OPS))}）")
    actual = row[column]
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "contains":
        return expected in actual
    left = _parse_number(actual)
    right = _parse_number(expected)
    if left is None or right is None:
        raise ValueError(f"列 {column} 的值不能按数字比较：{actual!r} {op} {expected!r}")
    if op == "gt":
        return left > right
    if op == "gte":
        return left >= right
    if op == "lt":
        return left < right
    return left <= right


def _metric_value(rows: list[dict[str, str]], metric: dict[str, Any]) -> tuple[str, int | float, int]:
    agg = str(metric.get("agg") or "count")
    column = str(metric.get("column") or "")
    if agg not in _AGGS:
        raise ValueError(f"不支持的汇总：{agg}（可用 {'/'.join(sorted(_AGGS))}）")
    if agg == "count":
        return "count", len(rows), 0
    if not column or (rows and column not in rows[0]):
        raise ValueError(f"汇总列不存在：{column or '（未填）'}")
    values = [row[column] for row in rows]
    if agg == "count_distinct":
        return f"{column}_count_distinct", len({value for value in values if value}), 0
    numbers: list[float] = []
    skipped = 0
    for value in values:
        if not value:
            continue
        number = _parse_number(value)
        if number is None:
            skipped += 1
        else:
            numbers.append(number)
    key = f"{column}_{agg}"
    if not numbers:
        return key, None, skipped
    if agg == "sum":
        return key, round(sum(numbers), 4), skipped
    if agg == "mean":
        return key, round(sum(numbers) / len(numbers), 4), skipped
    if agg == "min":
        return key, min(numbers), skipped
    return key, max(numbers), skipped


def make_clean_table_tool(*, base_dir: str, owner: str | None = None) -> Callable[..., Any]:
    base = Path(base_dir).resolve()

    def clean_table(
        file_name: str,
        key_columns: list[str] | str | None = None,
        sheet: str | None = None,
    ) -> dict[str, Any]:
        name = normalize_doc_name(file_name, owner)
        target = check_inside_base(base, name)
        if not target.is_file():
            raise FileNotFoundError(f"文件不存在：{file_name}")
        headers, rows, used_sheet = load_table_grid(target, sheet or None)
        keys = [str(item) for item in _as_list(key_columns)]
        cleaned = clean_grid(headers, rows, keys)
        clean_id = _write_clean(
            base,
            cleaned["columns"],
            cleaned["rows"],
            {"source": target.name, "sheet": used_sheet, "columns": cleaned["columns"]},
        )
        preview = cleaned["rows"][:_PREVIEW]
        return {
            "clean_id": clean_id,
            "source": target.name,
            "sheet": used_sheet,
            "columns": cleaned["columns"],
            "rows_in": cleaned["rows_in"],
            "rows_out": cleaned["rows_out"],
            "dropped_empty_rows": cleaned["dropped_empty_rows"],
            "dropped_duplicate_rows": cleaned["dropped_duplicate_rows"],
            "dropped_repeated_header": cleaned["dropped_repeated_header"],
            "dropped_empty_columns": cleaned["dropped_empty_columns"],
            "header_renames": cleaned["header_renames"],
            "key_columns": cleaned["key_columns"],
            "missing_key_rows": cleaned["missing_key_rows"],
            "column_missing": cleaned["column_missing"],
            "numeric_issues": cleaned["numeric_issues"],
            "preview": preview,
            "note": "原文件未改。后续分析只能调用 analyze_table，并传入这个 clean_id。",
        }

    clean_table.__name__ = "clean_table"
    return clean_table


def make_analyze_table_tool(*, base_dir: str, owner: str | None = None) -> Callable[..., Any]:
    del owner  # 分析只认 clean_id，目录已经是该用户的上传目录
    base = Path(base_dir).resolve()

    def analyze_table(
        clean_id: str,
        group_by: list[str] | str | None = None,
        metrics: list[dict[str, Any]] | dict[str, Any] | None = None,
        filters: list[dict[str, Any]] | dict[str, Any] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        headers, grid, meta = _load_clean(base, clean_id)
        records = [dict(zip(headers, _align(row, len(headers)), strict=False)) for row in grid]
        groups = [str(item) for item in _as_list(group_by)]
        unknown = [name for name in groups if name not in headers]
        if unknown:
            raise ValueError(f"分组列不存在：{'、'.join(unknown)}。现有列：{'、'.join(headers)}")
        filter_items = _as_list(filters)
        if any(not isinstance(item, dict) for item in filter_items):
            raise ValueError("filters 需要是 {column, op, value} 对象的列表")
        matched = [row for row in records if all(_match_filter(row, item) for item in filter_items)]
        metric_items = _as_list(metrics) or [{"agg": "count"}]
        if any(not isinstance(item, dict) for item in metric_items):
            raise ValueError("metrics 需要是 {column, agg} 对象的列表")

        buckets: dict[tuple[str, ...], list[dict[str, str]]] = {}
        for row in matched:
            key = tuple(row[name] for name in groups)
            buckets.setdefault(key, []).append(row)

        skipped: dict[str, int] = {}
        result_rows: list[dict[str, Any]] = []
        for key, bucket in buckets.items():
            item: dict[str, Any] = {name: value for name, value in zip(groups, key, strict=False)}
            for metric in metric_items:
                field, value, skip = _metric_value(bucket, metric)
                item[field] = value
                if skip:
                    skipped[field] = skipped.get(field, 0) + skip
            result_rows.append(item)

        if result_rows:
            sort_key = _metric_value([], metric_items[0])[0]
            result_rows.sort(
                key=lambda row: (row.get(sort_key) is not None, row.get(sort_key) or 0),
                reverse=True,
            )

        cap = max(1, min(int(limit or 50), _MAX_GROUPS))
        return {
            "clean_id": clean_id,
            "source": meta.get("source"),
            "rows_in": len(records),
            "rows_matched": len(matched),
            "group_by": groups,
            "groups": result_rows[:cap],
            "truncated": len(result_rows) > cap,
            "skipped_non_numeric": skipped,
            "note": "数字只来自清洗后的表。不能转成数字的格子已从 sum/mean/min/max 中跳过，没有当成 0。",
        }

    analyze_table.__name__ = "analyze_table"
    return analyze_table
