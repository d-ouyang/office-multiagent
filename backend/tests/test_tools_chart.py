"""render_chart：数字只来自清洗表，SVG 保留中文文字，并写入 asset。"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.orchestration.tools_chart import make_render_chart_tool
from app.orchestration.tools_table import make_clean_table_tool


def _ready(tmp_path):
    (tmp_path / "订单.csv").write_text(
        "月份,地区,金额\n1月,上海,10\n2月,上海,5\n1月,北京,3\n2月,北京,待定\n",
        encoding="utf-8",
    )
    cleaned = make_clean_table_tool(base_dir=str(tmp_path))("订单.csv")
    return cleaned["clean_id"]


def test_bar_line_pie_heatmap_and_chinese_text(tmp_path):
    clean_id = _ready(tmp_path)
    tool = make_render_chart_tool(base_dir=str(tmp_path))
    bar = tool(clean_id, "bar", x="地区", y="金额", title="地区金额")
    svg = (tmp_path / bar["file_name"]).read_text(encoding="utf-8")
    assert svg.startswith("<?xml") or "<svg" in svg
    assert "上海" in svg
    assert "地区金额" in svg
    assert bar["skipped_non_numeric"] == 1
    line = tool(clean_id, "line", x="月份", y="金额", series="地区")
    assert (tmp_path / line["file_name"]).is_file()
    pie = tool(clean_id, "pie", x="地区", y="金额")
    assert pie["format"] == "pie"
    heat = tool(clean_id, "heatmap", x="月份", y="金额", series="地区")
    assert "svg" in heat["file_name"]


def test_pie_rejects_negative_and_unknown_chart(tmp_path):
    (tmp_path / "t.csv").write_text("类,值\nA,-1\nB,2\n", encoding="utf-8")
    clean_id = make_clean_table_tool(base_dir=str(tmp_path))("t.csv")["clean_id"]
    tool = make_render_chart_tool(base_dir=str(tmp_path))
    with pytest.raises(ValueError, match="负数"):
        tool(clean_id, "pie", x="类", y="值")
    with pytest.raises(ValueError, match="不支持的图表"):
        tool(clean_id, "radar", x="类", y="值")


def test_scatter_hist_and_asset_row(tmp_path):
    (tmp_path / "点.csv").write_text("横,纵\n1,2\n2,4\n坏,1\n", encoding="utf-8")
    clean_id = make_clean_table_tool(base_dir=str(tmp_path))("点.csv")["clean_id"]
    eng = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE asset (id TEXT PRIMARY KEY, task_id TEXT, user_id INTEGER, "
            "type TEXT, name TEXT, rel_path TEXT, storage_url TEXT)"
        ))
    tool = make_render_chart_tool(base_dir=str(tmp_path), engine=eng, user_id=7, task_id="run-1")
    scatter = tool(clean_id, "scatter", x="横", y="纵", title="散点")
    assert scatter["points"] == 2
    assert scatter["recorded"] is True
    hist = tool(clean_id, "hist", x="纵", bins=4)
    assert hist["format"] == "hist"
    with eng.connect() as conn:
        rows = conn.execute(text("SELECT id, user_id, rel_path FROM asset")).all()
    assert len(rows) == 2
    assert rows[0][1] == 7
    assert str(rows[0][2]).startswith("_out/g-")


def test_time_axis_labels_sorted_chronologically_and_not_truncated(tmp_path):
    """p6.48 hotfix：时间语义标签一律按时间先后排序且不按 top_n 截断。

    线上实测：柱状图"9月排第一"（值降序所致）、折线图"标题 2025-01~2026-09
    却断在 2026-01"（top_n=13 把 21 个月砍剩 13 个）。
    """
    from app.orchestration.tools_chart import _ordered_labels, _time_key

    # 柱状图：YYYY-MM 全时间轴按时间排，不按值排
    labels = ["2025-09", "2025-01", "2026-01", "2025-12"]
    totals = {"2025-09": 9, "2025-01": 1, "2026-01": 8, "2025-12": 5}
    assert _ordered_labels(labels, totals, "bar", 3) == ["2025-01", "2025-09", "2025-12", "2026-01"]

    # 折线图：21 个月不受 top_n=13 截断
    months = [f"2025-{m:02d}" for m in range(1, 13)] + [f"2026-{m:02d}" for m in range(1, 10)]
    full = _ordered_labels(months, {m: 1 for m in months}, "line", 13)
    assert full == months  # 2025-01 → 2026-09 完整时间序

    # 季度轴按时间排（2025Q1 < 2025Q3 < 2026Q1）
    assert _ordered_labels(
        ["2026Q1", "2025Q3", "2025Q1"], {l: 1 for l in ["2026Q1", "2025Q3", "2025Q1"]}, "bar", 12
    ) == ["2025Q1", "2025Q3", "2026Q1"]

    # 月份序号 1~12（query_orders 副本 month 列）按 1→12 排，不按值排
    assert _ordered_labels(["12", "1", "2"], {"12": 9, "1": 5, "2": 7}, "bar", 12) == ["1", "2", "12"]

    # 非时间标签保持原行为：柱状按值降序取 top_n
    assert _ordered_labels(["门店A", "门店B", "门店C"], {"门店A": 1, "门店B": 9, "门店C": 5}, "bar", 2) == ["门店B", "门店C"]

    # 单标签不成时间轴（无法判断），维持原行为
    assert _time_key("门店A") is None
    assert _time_key("2025-01") == (2025, 1, 0)
    assert _time_key("9月") == (0, 9, 0)


def test_render_chart_full_year_line_not_truncated(tmp_path):
    """p6.48 hotfix：跨年逐月数据画折线，visual labels 必须覆盖全部月份。"""
    rows = "\n".join(
        [f"年月,金额\n2025-{m:02d},{m}" for m in range(1, 13)]
        + [f"2026-{m:02d},{m + 12}" for m in range(1, 10)]
    )
    (tmp_path / "月销.csv").write_text(rows + "\n", encoding="utf-8")
    clean_id = make_clean_table_tool(base_dir=str(tmp_path))("月销.csv")["clean_id"]
    tool = make_render_chart_tool(base_dir=str(tmp_path))
    result = tool(clean_id, "line", x="年月", y="金额", title="2025年1月至2026年9月的逐月销售走势")
    visual = result["visual"]
    assert len(visual["labels"]) == 21
    assert visual["labels"][0] == "2025-01"
    assert visual["labels"][-1] == "2026-09"
