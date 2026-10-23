"""p6.30：export_orders 明细导出 + render_chart(export_id)/嵌图 + planner 隔离/折叠 + assets 链。"""
import csv

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.events import EventType
from app.core.planner import plan as run_plan
from app.core.router import decide
from app.orchestration.graph import run_task
from app.orchestration.orchestrator import compose_subtask_text
from app.orchestration.react import AgentResult, Step, run_react
from app.orchestration.tools_export import make_export_orders_tool


@pytest.fixture
def engine():
    from app.orchestration.orders_seed import COLUMNS

    eng = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    cols = ", ".join(f"{name} TEXT" for name in COLUMNS)
    with eng.begin() as conn:
        conn.execute(text(f"CREATE TABLE guoquan_orders ({cols})"))
        conn.execute(text("CREATE TABLE asset (id TEXT PRIMARY KEY, task_id TEXT, type TEXT, storage_url TEXT, user_id INTEGER, name TEXT, rel_path TEXT)"))
        conn.execute(
            text(
                "INSERT INTO guoquan_orders "
                "(order_no, order_create_time, order_status, order_channel, store_name, store_address, "
                "pay_amount, total_amount, discount_amount, refund_amount, order_type, fulfillment_type, "
                "member_level, goods_quantity, receiver_phone) VALUES "
                "('GQ1','2026-01-02 17:43:52','已完成','微信小程序','锅圈食汇(天山店)','上海市长宁区天山路1号',"
                "'10.50','12.50','2.00','0','普通订单','门店自提','金卡会员','2','13800000000'),"
                "('GQ2','2026-03-01 12:00:00','已取消','门店扫码','锅圈食汇(迎江店)','安庆市迎江区华中路1号',"
                "'0','8.00','0','0','普通订单','门店自提','普通会员','1',''),"
                "('GQ3','2026-06-20 09:00:00','已完成','美团外卖','锅圈食汇(大场店)','上海市宝山区大场镇1号',"
                "'20.00','22.00','2.00','0','拼团订单','平台外卖配送','银卡会员','3','13600000000')"
            )
        )
    return eng


@pytest.fixture
def out_dir(tmp_path):
    d = tmp_path / "upload" / "dev"
    d.mkdir(parents=True)
    return d


def _export(engine, out_dir, **kw):
    tool = make_export_orders_tool(engine, base_dir=str(out_dir), user_id=1)
    kw.setdefault("date_from", "2026-01-01")
    kw.setdefault("date_to", "2026-12-31")
    return tool(**kw)


# --------------------------------------------------------------------------- #
# export_orders
# --------------------------------------------------------------------------- #

def test_export_csv_default_fields(engine, out_dir):
    out = _export(engine, out_dir, city="上海")
    assert "error" not in out
    assert out["export_id"].startswith("e-") and len(out["export_id"]) == 18
    assert out["row_count"] == 2  # 上海两单
    assert out["columns"] == ["下单时间", "订单号", "城市", "门店", "用户(脱敏)", "是否线上", "平台", "销售金额", "订单状态"]
    path = out_dir / out["file_name"]
    assert path.is_file()
    with path.open(encoding="utf-8-sig", newline="") as h:
        grid = list(csv.reader(h))
    assert grid[0] == out["columns"]
    by_no = {row[1]: row for row in grid[1:]}
    gq1 = by_no["GQ1"]
    assert gq1[4] == "138****0000"  # 手机号脱敏
    assert gq1[5] == "线上"  # 微信小程序 → 线上
    assert "13800000000" not in path.read_text(encoding="utf-8-sig")  # 原始号码不落盘


def test_export_derives_offline_and_omits_missing_fields(engine, out_dir):
    out = _export(engine, out_dir, fields=["销售金额", "门店", "用户", "是否线上", "平台", "支付方式", "发票抬头"])
    assert "error" not in out
    assert "支付方式" in out["omitted"] and "整列省略" in out["omitted"]["支付方式"]
    assert "发票抬头" in out["omitted"]  # 认不出的字段也省略，不报错不瞎猜
    assert out["columns"] == ["销售金额", "门店", "用户(脱敏)", "是否线上", "平台"]
    # GQ2 是门店扫码 → 线下
    path = out_dir / out["file_name"]
    content = path.read_text(encoding="utf-8-sig")
    assert "线下" in content and "线上" in content
    # 支付方式列绝不存在
    assert "支付方式" not in out["columns"]


def test_export_xlsx_and_filters(engine, out_dir):
    out = _export(engine, out_dir, format="xlsx", order_status="已完成")
    assert out["format"] == "xlsx" and out["row_count"] == 2
    assert (out_dir / out["file_name"]).is_file()
    # 非法状态如实拒绝
    bad = _export(engine, out_dir, order_status="已发货")
    assert "error" in bad


def test_export_requires_date_range_and_handles_empty(engine, out_dir):
    assert "必须带" in _export(engine, out_dir, date_from=None, date_to=None)["error"]
    empty = _export(engine, out_dir, date_from="2020-01-01", date_to="2020-12-31")
    assert "没有订单" in empty["error"]


def test_render_chart_from_export_id(engine, out_dir):
    exp = _export(engine, out_dir, city="上海", fields=["下单时间", "销售金额"])
    from app.orchestration.tools_chart import make_render_chart_tool

    tool = make_render_chart_tool(base_dir=str(out_dir), engine=engine, user_id=1)
    out = tool(clean_id=exp["export_id"], chart="bar", x="下单时间", y="销售金额", title="上海销售趋势")
    assert out["doc_id"].startswith("g-")
    assert (out_dir / out["file_name"]).is_file()
    assert (out_dir / out["png_file"]).is_file()  # p6.30：同时产出 png
    assert "订单明细导出" in (out.get("source") or "")
    # 原始文件名/非法 id 拒绝
    with pytest.raises(ValueError):
        tool(clean_id="sales.csv", chart="bar", x="下单时间", y="销售金额")


def test_render_chart_from_xlsx_export(engine, out_dir):
    """真跑回归：模型选 xlsx 导出时，render_chart 也要能读回（曾只读 csv 报"找不到导出表"）。"""
    exp = _export(engine, out_dir, city="上海", fields=["下单时间", "销售金额"], format="xlsx")
    from app.orchestration.tools_chart import make_render_chart_tool

    out = make_render_chart_tool(base_dir=str(out_dir), engine=engine, user_id=1)(
        clean_id=exp["export_id"], chart="line", x="下单时间", y="销售金额", title="趋势"
    )
    assert (out_dir / out["file_name"]).is_file()
    assert out["points"] >= 2


def test_write_document_embeds_image(engine, out_dir):
    from app.orchestration.tools_chart import make_render_chart_tool
    from app.orchestration.tools_write import make_write_document_tool

    exp = _export(engine, out_dir, city="上海", fields=["下单时间", "销售金额"])
    chart = make_render_chart_tool(base_dir=str(out_dir), engine=engine, user_id=1)(
        clean_id=exp["export_id"], chart="line", x="下单时间", y="销售金额", title="趋势"
    )
    writer = make_write_document_tool(base_dir=str(out_dir), engine=engine, user_id=1)
    # md：相对引用
    md = writer(title="销售总结", content="# 销售总结\n\n结论……", image_file=chart["png_file"])
    body = (out_dir / md["file_name"]).read_text(encoding="utf-8")
    assert f"![{chart['png_file'].split('/')[-1]}]({chart['png_file'].split('/')[-1]})" in body
    # docx：真嵌入（png 存在）
    docx = writer(title="销售总结", content="销售总结正文", format="docx", image_file=chart["png_file"])
    assert (out_dir / docx["file_name"]).stat().st_size > 10_000  # 有图明显大于纯文本
    # 非法 image_file 拒绝
    with pytest.raises(ValueError):
        writer(title="x", content="y", image_file="../../etc/passwd.png")


def test_generated_file_whitelist_accepts_export_and_png():
    from app.api.routes import _OUT_FILE

    assert _OUT_FILE.match("e-0123456789abcdef.csv")
    assert _OUT_FILE.match("g-0123456789abcdef.png")
    assert _OUT_FILE.match("w-0123456789abcdef.docx")
    assert not _OUT_FILE.match("e-xxx.csv")
    assert not _OUT_FILE.match("../evil.csv")


# --------------------------------------------------------------------------- #
# P0：planner 输入隔离 + 折叠
# --------------------------------------------------------------------------- #

TEXT = "拿到上海今年1月到现在的所有订单，形成表格，表格里要包含销售金额、门店、用户、是否是线上还是线下、支付方式、平台等信息。然后根据这个表格写一份销售总结文档，文档中最好有图表展示销售趋势，并给出销售建议。"


def test_planner_on_raw_text_is_clean():
    p = run_plan(TEXT)
    d = decide(p)
    assert "rag" not in p.intents
    assert d.mode == "single"
    assert d.primary_agent == "data_analysis"


def test_planner_fold_visualization_into_analysis():
    """分析+图表 → 折叠成 analysis 单意图（图表是内嵌能力，不拆独立子任务）。"""
    p = run_plan("分析10月销售情况并画图表")
    assert "visualization" not in p.intents
    assert p.intents == ["analysis"]


def test_planner_keeps_viz_when_alone():
    """只要图（不上传表清洗后画图）仍走 visualization Agent。"""
    p = run_plan("把我的表画成饼图")
    assert p.intents == ["visualization"]


def test_run_task_planner_uses_raw_text_not_injected_blocks():
    """P0 回归：text（带注入块）里含"制度"不再劫持意图——planner 只看 raw_text。"""
    polluted = "【用户长期记忆】\n- 报销口径以财务制度 2026 版为准\n\n【本轮问题】\n" + TEXT
    events: list = []
    result, events = run_task(
        polluted,
        raw_text=TEXT,
        sink=events.append,
    )
    thinks = [e.data.get("delta", "") for e in events if e.type == "thinking_delta"]
    plan_line = next((t for t in thinks if "识别意图" in t), "")
    assert "rag" not in plan_line, plan_line


# --------------------------------------------------------------------------- #
# P1-c：assets 传递 + multi 汇总
# --------------------------------------------------------------------------- #

def test_compose_subtask_text_lists_upstream_assets():
    upstream = {
        "analysis": AgentResult(
            final="已导出明细",
            steps=[],
            iterations=1,
            assets=[{"tool": "export_orders", "file_name": "_out/e-abc.csv",
                     "display_name": "e-abc.csv", "export_id": "e-0123456789abcdef"}],
        )
    }
    text = compose_subtask_text("画图并写文档", upstream, request_text="基于表格画趋势图")
    assert "【上游产物" in text
    assert "e-0123456789abcdef" in text and "_out/e-abc.csv" in text


def test_react_collects_assets_from_tool_outputs():
    from app.orchestration.tools import ToolRegistry
    from app.orchestration.react import StubBrain

    class TwoStepBrain:
        def __init__(self):
            self.calls = 0

        def next_step(self, task, history):
            self.calls += 1
            if self.calls == 1:
                return Step(thought="导出", action="export_orders", action_input={})
            return Step(thought="完成", final="已导出 e-0123456789abcdef.csv")

    reg = ToolRegistry()
    reg.register("export_orders", lambda **kw: {
        "export_id": "e-0123456789abcdef", "file_name": "_out/e-0123456789abcdef.csv",
        "display_name": "e-0123456789abcdef.csv", "format": "csv",
    })
    out = run_react("导出", TwoStepBrain(), reg)
    assert out.assets and out.assets[0]["file_name"] == "_out/e-0123456789abcdef.csv"
    assert out.assets[0]["export_id"] == "e-0123456789abcdef"


def test_export_id_frozen_in_settings_default():
    """导出行数上限可配置（settings.export_orders_max_rows）。"""
    assert settings.export_orders_max_rows >= 1000
