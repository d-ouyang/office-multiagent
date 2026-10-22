"""上传表格清洗与分析：不改原文件，分析只认 clean_id。"""
import pytest
from openpyxl import Workbook

from app.orchestration.tools_table import make_analyze_table_tool, make_clean_table_tool


def _clean(tmp_path):
    return make_clean_table_tool(base_dir=str(tmp_path))


def _analyze(tmp_path):
    return make_analyze_table_tool(base_dir=str(tmp_path))


def test_clean_drops_empty_duplicate_header_and_missing_keys(tmp_path):
    (tmp_path / "订单.csv").write_text(
        "地区,金额,备注\n"
        "上海,\"1,234\",\n"
        "\n"
        "上海,\"1,234\",null\n"
        " ,8,无\n"
        "北京,3,有\n"
        "地区,金额,备注\n",
        encoding="utf-8",
    )
    out = _clean(tmp_path)("订单.csv", key_columns=["地区"])
    assert out["rows_in"] == 6
    assert out["dropped_empty_rows"] == 1
    assert out["dropped_duplicate_rows"] == 1
    assert out["dropped_repeated_header"] == 1
    assert out["missing_key_rows"] == 1
    assert out["rows_out"] == 2
    assert (tmp_path / "订单.csv").read_text(encoding="utf-8").startswith("地区,金额")
    assert ["上海", "1,234", ""] in out["preview"]
    assert any(item["column"] == "金额" and item["parsed"] >= 1 for item in out["numeric_issues"]) is False


def test_clean_drops_empty_column_and_trims(tmp_path):
    (tmp_path / "t.csv").write_text("地区,空列\n\u3000上海\u3000,\n北京,\n", encoding="utf-8")
    out = _clean(tmp_path)("t.csv")
    assert out["dropped_empty_columns"] == ["空列"]
    assert out["columns"] == ["地区"]
    assert out["preview"][0] == ["上海"]


def test_clean_unknown_key_is_honest(tmp_path):
    (tmp_path / "t.csv").write_text("地区,金额\n上海,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="没有这些关键列"):
        _clean(tmp_path)("t.csv", key_columns=["订单号"])


def test_clean_xlsx_and_analyze_group_sum(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.title = "订单"
    sheet.append(["地区", "金额"])
    sheet.append(["上海", 10])
    sheet.append(["北京", 5])
    sheet.append(["上海", 2])
    book.save(tmp_path / "订单.xlsx")
    cleaned = _clean(tmp_path)("订单.xlsx", sheet="订单")
    result = _analyze(tmp_path)(
        cleaned["clean_id"],
        group_by="地区",
        metrics=[{"column": "金额", "agg": "sum"}],
        filters={"column": "地区", "op": "eq", "value": "上海"},
    )
    assert result["rows_matched"] == 2
    assert result["groups"] == [{"地区": "上海", "金额_sum": 12}]
    assert result["skipped_non_numeric"] == {}


def test_analyze_skips_non_numeric_and_rejects_raw_name(tmp_path):
    (tmp_path / "t.csv").write_text("金额\n10\n待定\n", encoding="utf-8")
    cleaned = _clean(tmp_path)("t.csv")
    result = _analyze(tmp_path)(
        cleaned["clean_id"], metrics={"column": "金额", "agg": "sum"}
    )
    assert result["groups"][0]["金额_sum"] == 10
    assert result["skipped_non_numeric"]["金额_sum"] == 1
    (tmp_path / "bad.csv").write_text("地区,金额\n北京,待定\n", encoding="utf-8")
    only_text = _clean(tmp_path)("bad.csv")
    grouped = _analyze(tmp_path)(
        only_text["clean_id"],
        group_by="地区",
        metrics={"column": "金额", "agg": "sum"},
    )
    assert grouped["groups"][0]["金额_sum"] is None
    with pytest.raises(ValueError, match="clean_id"):
        _analyze(tmp_path)("t.csv")


def test_clean_rejects_path_escape(tmp_path):
    outside = tmp_path.parent / "secret.csv"
    outside.write_text("a\n1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="非法路径"):
        _clean(tmp_path)("../secret.csv")
