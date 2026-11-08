"""用 Matplotlib 按清洗后的表画图，导出 SVG。

几何和汇总值由代码计算。svg.fonttype=none，文字保留成字符，中文交给浏览器字体，
避免服务器没有中文字体时把字画成方框。模型不能传入数据点。
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .tools_store import finish_output, new_output_id, output_file
from .tools_table import _as_list, _load_clean, _match_filter, _parse_number

_EXPORT_ID_RE = __import__("re").compile(r"^e-[0-9a-f]{16}$")

_CHARTS = ("bar", "barh", "line", "area", "pie", "scatter", "heatmap", "hist")
_AGGS = ("sum", "mean", "count", "min", "max")
_COLORS = ("#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2", "#B279A2", "#FF9DA6", "#9D755D")


def _columns(value: Any) -> list[str]:
    return [str(item) for item in _as_list(value)]


def _require(headers: list[str], name: str, label: str) -> None:
    if not name or name not in headers:
        raise ValueError(f"{label}不存在：{name or '（未填）'}。现有列：{'、'.join(headers)}")


def _reduce(values: list[float], agg: str) -> float | None:
    if agg == "count":
        return float(len(values))
    if not values:
        return None
    if agg == "sum":
        return round(sum(values), 4)
    if agg == "mean":
        return round(sum(values) / len(values), 4)
    if agg == "min":
        return min(values)
    if agg == "max":
        return max(values)
    raise ValueError(f"不支持的汇总：{agg}（可用 {'/'.join(_AGGS)}）")


def _numeric_bucket(rows: list[dict[str, str]], column: str, agg: str) -> tuple[float | None, int]:
    if agg == "count":
        return float(len(rows)), 0
    numbers: list[float] = []
    skipped = 0
    for row in rows:
        raw = row.get(column, "")
        if not raw:
            continue
        number = _parse_number(raw)
        if number is None:
            skipped += 1
        else:
            numbers.append(number)
    return _reduce(numbers, agg), skipped


def _ordered_labels(labels: list[str], totals: dict[str, float], chart: str, top_n: int) -> list[str]:
    if chart in {"line", "area"}:
        def key(label: str) -> tuple:
            number = _parse_number(label)
            return (number is None, number if number is not None else label)
        ordered = sorted(labels, key=key)
    else:
        ordered = sorted(labels, key=lambda label: totals.get(label, 0), reverse=True)
    return ordered[:top_n]


def _draw(path: Path, chart: str, title: str, payload: dict[str, Any], *, fmt: str = "svg") -> None:
    import matplotlib

    matplotlib.use("Agg", force=False)
    matplotlib.rcParams["svg.fonttype"] = "none"
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt

    import warnings

    fig, ax = plt.subplots(figsize=(9, 5))
    try:
        warnings.filterwarnings("ignore", message="Glyph .* missing from font")
        if chart == "heatmap":
            grid = payload["grid"]
            image = ax.imshow(grid, cmap="Blues", aspect="auto")
            ax.set_xticks(range(len(payload["xlabels"])), labels=payload["xlabels"], rotation=30, ha="right")
            ax.set_yticks(range(len(payload["ylabels"])), labels=payload["ylabels"])
            fig.colorbar(image, ax=ax)
            if len(payload["xlabels"]) <= 8 and len(payload["ylabels"]) <= 8:
                for i, row in enumerate(grid):
                    for j, value in enumerate(row):
                        if value == value:
                            ax.text(j, i, f"{value:g}", ha="center", va="center", color="#1a1a1a")
        elif chart == "hist":
            ax.hist(payload["values"], bins=payload["bins"], color=_COLORS[0], edgecolor="white")
            ax.set_xlabel(payload["xlabel"])
            ax.set_ylabel("频数")
        elif chart == "scatter":
            ax.scatter(payload["xs"], payload["ys"], color=_COLORS[0], alpha=0.85)
            ax.set_xlabel(payload["xlabel"])
            ax.set_ylabel(payload["ylabel"])
        elif chart == "pie":
            ax.pie(
                payload["values"],
                labels=payload["labels"],
                colors=_COLORS[: len(payload["labels"])],
                autopct="%1.0f%%",
                startangle=90,
            )
            ax.set_ylabel("")
        else:
            series = payload["series"]
            labels = payload["labels"]
            positions = list(range(len(labels)))
            if chart == "barh":
                for index, (name, values) in enumerate(series.items()):
                    offset = [p + index / max(len(series), 1) * 0.8 for p in positions]
                    ax.barh(offset, values, height=0.8 / max(len(series), 1), label=name, color=_COLORS[index % len(_COLORS)])
                ax.set_yticks(positions, labels=labels)
            elif chart == "bar":
                width = 0.8 / max(len(series), 1)
                for index, (name, values) in enumerate(series.items()):
                    offset = [p + index * width for p in positions]
                    ax.bar(offset, values, width=width, label=name, color=_COLORS[index % len(_COLORS)])
                ax.set_xticks([p + width * (len(series) - 1) / 2 for p in positions], labels=labels, rotation=30, ha="right")
            else:
                for index, (name, values) in enumerate(series.items()):
                    ax.plot(labels, values, marker="o", label=name, color=_COLORS[index % len(_COLORS)])
                    if chart == "area":
                        ax.fill_between(labels, values, alpha=0.18, color=_COLORS[index % len(_COLORS)])
                ax.tick_params(axis="x", labelrotation=30)
            if len(series) > 1:
                ax.legend()
            ax.set_ylabel(payload["ylabel"])
        ax.set_title(title)
        fig.tight_layout()
        fig.savefig(path, format=fmt)
    finally:
        plt.close(fig)


def _prepare(records: list[dict[str, str]], headers: list[str], chart: str, x: str, y_cols: list[str], series: str, agg: str, top_n: int, bins: int) -> tuple[dict[str, Any], int, int]:
    skipped = 0
    used = 0
    if chart == "hist":
        column = y_cols[0] if y_cols else x
        _require(headers, column, "直方图的列")
        values = []
        for row in records:
            number = _parse_number(row.get(column, ""))
            if number is None:
                if row.get(column, ""):
                    skipped += 1
            else:
                values.append(number)
        if not values:
            raise ValueError(f"列 {column} 没有可以分箱的数字")
        return {"values": values, "bins": bins, "xlabel": column}, len(values), skipped
    if chart == "scatter":
        if len(y_cols) != 1:
            raise ValueError("散点图需要一个 x 列和一个 y 列")
        _require(headers, x, "x 列")
        _require(headers, y_cols[0], "y 列")
        xs: list[float] = []
        ys: list[float] = []
        for row in records:
            left = _parse_number(row.get(x, ""))
            right = _parse_number(row.get(y_cols[0], ""))
            if left is None or right is None:
                skipped += 1
                continue
            xs.append(left)
            ys.append(right)
            if len(xs) >= 500:
                break
        if not xs:
            raise ValueError("散点图没有成对的数字")
        return {"xs": xs, "ys": ys, "xlabel": x, "ylabel": y_cols[0]}, len(xs), skipped

    _require(headers, x, "分类列")
    if chart == "heatmap":
        if not series or len(y_cols) != 1:
            raise ValueError("热力图需要 x、series 两个分类列，以及一个数值列 y")
        _require(headers, series, "series 列")
        _require(headers, y_cols[0], "数值列")
    elif agg != "count":
        if len(y_cols) < 1:
            raise ValueError("除了 count，还需要数值列 y")
        for name in y_cols:
            _require(headers, name, "数值列")
    if series and len(y_cols) > 1:
        raise ValueError("多个数值列和 series 不能同时用")
    if series:
        _require(headers, series, "series 列")

    buckets: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in records:
        label = row.get(x, "") or "（空）"
        serie = row.get(series, "") if series else (y_cols[0] if y_cols else "数量")
        if not series and len(y_cols) > 1:
            for name in y_cols:
                buckets[(label, name)].append(row)
        else:
            buckets[(label, serie or "数量")].append(row)

    totals: dict[str, float] = defaultdict(float)
    matrix: dict[str, dict[str, float]] = defaultdict(dict)
    for (label, serie), rows in buckets.items():
        column = y_cols[0] if len(y_cols) == 1 else serie
        if agg == "count":
            value, bad = float(len(rows)), 0
        else:
            value, bad = _numeric_bucket(rows, column if column in headers else y_cols[0], agg)
        skipped += bad
        if value is None:
            continue
        matrix[serie][label] = value
        totals[label] += value
        used += len(rows)
    labels = _ordered_labels(list(totals), totals, chart, top_n)
    if not labels:
        raise ValueError("没有可以绘制的数字")
    if chart == "heatmap":
        ylabels = list(matrix)
        grid = [[matrix[row].get(col, float("nan")) for col in labels] for row in ylabels]
        return {"grid": grid, "xlabels": labels, "ylabels": ylabels, "ylabel": y_cols[0]}, used, skipped
    if chart == "pie":
        if len(y_cols) > 1:
            raise ValueError("饼图只接受一个数值列")
        first = next(iter(matrix))
        pairs = [(label, matrix[first].get(label, 0)) for label in labels]
        if any(value < 0 for _, value in pairs):
            raise ValueError("饼图不能包含负数")
        if len(pairs) > 8:
            head, tail = pairs[:7], pairs[7:]
            pairs = head + [("其他", round(sum(value for _, value in tail), 4))]
        return {
            "labels": [label for label, _ in pairs],
            "values": [value for _, value in pairs],
            "ylabel": y_cols[0] if y_cols else "数量",
        }, used, skipped
    plotted = {name: [matrix[name].get(label, 0) for label in labels] for name in matrix}
    return {"labels": labels, "series": plotted, "ylabel": "、".join(y_cols) if y_cols else "数量"}, used, skipped


def _finite(value: Any) -> Any:
    if isinstance(value, float) and value != value:
        return None
    return value


def chart_visual(kind: str, title: str, payload: dict[str, Any]) -> dict[str, Any]:
    """给前端 ECharts 的结构。数与落盘的 svg/png 来自同一次汇总。"""
    spec: dict[str, Any] = {"kind": "chart", "chart": kind, "title": title}
    if kind == "hist":
        spec.update(xlabel=payload.get("xlabel"), values=payload.get("values") or [], bins=payload.get("bins") or 10)
    elif kind == "scatter":
        spec.update(
            xlabel=payload.get("xlabel"),
            ylabel=payload.get("ylabel"),
            points=[[x, y] for x, y in zip(payload.get("xs") or [], payload.get("ys") or [], strict=False)],
        )
    elif kind == "heatmap":
        grid = [[_finite(cell) for cell in row] for row in (payload.get("grid") or [])]
        spec.update(xlabels=payload.get("xlabels") or [], ylabels=payload.get("ylabels") or [], grid=grid)
    elif kind == "pie":
        spec.update(labels=payload.get("labels") or [], values=payload.get("values") or [])
    else:
        series = [
            {"name": name, "data": values}
            for name, values in (payload.get("series") or {}).items()
        ]
        spec.update(labels=payload.get("labels") or [], series=series, ylabel=payload.get("ylabel"))
    return spec


def _load_table(base: Path, table_id: str) -> tuple[list[str], list[list[str]], dict[str, Any]]:
    """p6.30：clean_id（清洗表）与 export_id（订单明细导出）统一加载入口。"""
    if _EXPORT_ID_RE.match(table_id or ""):
        from .tools_export import load_export

        headers, grid = load_export(str(base), table_id)
        return headers, grid, {"source": "订单明细导出"}
    return _load_clean(base, table_id)


def make_render_chart_tool(
    *,
    base_dir: str,
    owner: str | None = None,
    engine: Any = None,
    user_id: int | None = None,
    task_id: str | None = None,
) -> Callable[..., Any]:
    del owner
    base = Path(base_dir).resolve()

    def render_chart(
        clean_id: str,
        chart: str,
        x: str,
        y: list[str] | str | None = None,
        series: str | None = None,
        agg: str = "sum",
        title: str | None = None,
        filters: list[dict[str, Any]] | dict[str, Any] | None = None,
        top_n: int = 12,
        bins: int = 10,
    ) -> dict[str, Any]:
        kind = (chart or "").strip().lower()
        if kind not in _CHARTS:
            raise ValueError(f"不支持的图表：{chart}（可用 {'/'.join(_CHARTS)}）")
        how = (agg or "sum").strip().lower()
        if how not in _AGGS:
            raise ValueError(f"不支持的汇总：{agg}（可用 {'/'.join(_AGGS)}）")
        # p6.30：clean_id（c-）与 export_id（e-，export_orders 产物）都接受，
        # 订单明细导出后可直接画图，不必再走 clean_table。
        tid = str(clean_id or "").strip()
        if not (_EXPORT_ID_RE.match(tid) or tid.startswith("c-")):
            raise ValueError(
                "clean_id 无效。请先调用 clean_table（上传表）或 export_orders（订单明细，e- 开头），"
                "不要把原始文件名传进来。"
            )
        headers, grid, meta = _load_table(base, tid)
        records = [dict(zip(headers, row + [""] * (len(headers) - len(row)), strict=False)) for row in grid]
        filter_items = _as_filter(filters)
        matched = [row for row in records if all(_match_filter(row, item) for item in filter_items)]
        if not matched:
            raise ValueError("过滤之后没有行，无法画图")
        y_cols = _columns(y)
        serie = (series or "").strip()
        limit = max(3, min(int(top_n or 12), 30))
        bin_count = max(3, min(int(bins or 10), 30))
        payload, used, skipped = _prepare(matched, headers, kind, str(x or ""), y_cols, serie, how, limit, bin_count)
        heading = (title or f"{meta.get('source') or '图表'}").strip()[:40] or "图表"
        doc_id = new_output_id("g")
        filename = f"{doc_id}.svg"
        target = output_file(base, filename)
        _draw(target, kind, heading, payload)
        # p6.30：同时产出 png（write_document 往 docx 里嵌图需要位图；svg 无法直接嵌 docx）。
        # png 只落盘不注册 asset——预览/嵌入走 documents/content 的文件存在性校验。
        png_filename = f"{doc_id}.png"
        _draw_png(output_file(base, png_filename), kind, heading, payload)
        rel = f"_out/{filename}"
        recorded = finish_output(
            engine,
            target,
            asset_id=doc_id,
            user_id=user_id,
            task_id=task_id,
            kind=kind,
            name=f"{heading}.svg",
            rel_path=rel,
        )
        return {
            "doc_id": doc_id,
            "file_name": rel,
            "png_file": f"_out/{png_filename}",
            "no_artifact": True,  # 2.1.0：过程已实时画图（visual），svg 不再进对话文件区；png 落盘供报告嵌图
            "display_name": f"{heading}.svg",
            "format": kind,
            "clean_id": clean_id,
            "source": meta.get("source"),
            "points": used,
            "skipped_non_numeric": skipped,
            "recorded": recorded,
            "visual": chart_visual(kind, heading, payload),
            "note": "图中的数只来自表格数据。界面用这份 visual 画图；svg/png 供下载和嵌进文档。",
        }

    render_chart.__name__ = "render_chart"
    return render_chart


def _draw_png(path: Path, chart: str, title: str, payload: dict[str, Any]) -> None:
    """p6.30：同 payload 画一份 png（docx 嵌图需要位图，svg 嵌不进 docx）。

    png 走系统字体渲染：容器里没有中文字体时中文会变方框——这是已知的显示退化，
    不阻断（svg 版本用 svg.fonttype=none 把文字留给浏览器渲染，不受影响）。
    """
    import matplotlib

    matplotlib.use("Agg", force=False)
    # png 需要真实字体文件；按常见中文字体优先探测一次，找不到就用默认（可能方框）
    try:
        from matplotlib import font_manager

        for family in ("Noto Sans CJK SC", "WenQuanYi Zen Hei", "PingFang SC",
                       "Microsoft YaHei", "SimHei", "Arial Unicode MS"):
            if any(f.name == family for f in font_manager.fontManager.ttflist):
                matplotlib.rcParams["font.family"] = family
                break
    except Exception:  # noqa: BLE001 - 字体探测失败不阻断
        pass
    matplotlib.rcParams["axes.unicode_minus"] = False
    _draw(path, chart, title, payload, fmt="png")


def _as_filter(value: Any) -> list[dict[str, Any]]:
    items = _as_list(value) if not isinstance(value, dict) else [value]
    if any(not isinstance(item, dict) for item in items):
        raise ValueError("filters 需要是 {column, op, value} 的列表")
    return items
