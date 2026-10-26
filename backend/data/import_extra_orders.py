"""把指定 CSV（orders_seed 英文表头）里的新订单补灌进 guoquan_orders。

与 ensure_orders_loaded 的区别：后者只在**空表**时导入；
本脚本给已初始化的库**增量补数据**，只插 order_no 不存在的行（幂等，可重复跑）。

用法（backend 容器内或挂了 data 卷的环境）：
    PYTHONPATH=/app python /app/data/import_extra_orders.py /app/data/<你的订单CSV>.csv
    （python 直接跑脚本时 sys.path[0] 是脚本目录，必须显式给 PYTHONPATH=/app）
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

from app.core.db import get_engine
from app.orchestration.orders_seed import COLUMNS, read_order_rows


def main() -> None:
    path = Path(sys.argv[1])
    rows = read_order_rows(path)
    engine = get_engine()
    stmt = text(
        f"INSERT INTO guoquan_orders ({', '.join(COLUMNS)}) "
        f"VALUES ({', '.join(':' + c for c in COLUMNS)})"
    )
    with engine.begin() as conn:
        existing = {r[0] for r in conn.execute(text("SELECT order_no FROM guoquan_orders"))}
        todo = [r for r in rows if r["order_no"] not in existing]
        if todo:
            conn.execute(stmt, todo)
        total = conn.execute(text("SELECT COUNT(*) FROM guoquan_orders")).scalar()
    print(f"CSV {len(rows)} 行，补插 {len(todo)} 行，库中现共 {total} 行")


if __name__ == "__main__":
    main()
