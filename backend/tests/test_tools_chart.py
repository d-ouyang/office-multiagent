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
