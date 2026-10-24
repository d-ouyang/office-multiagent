"""p6.31：文件预览升级——表格分页预览（大文件不截断）+ 原始文件下载。"""
import csv
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.main import app

SECRET = "test-secret-preview"
EID = "e-0123456789abcdef"


@pytest.fixture
def client(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with engine.begin() as c:
        c.execute(text("CREATE TABLE `user` (id INTEGER PRIMARY KEY, employee_id TEXT, username TEXT, role TEXT, model_pool_id INTEGER, token_version INTEGER NOT NULL DEFAULT 0, password_hash TEXT)"))
        c.execute(text("INSERT INTO `user` (id, employee_id, username, role) VALUES (1, 'EMP001', 'dev', 'user'), (2, 'EMP002', 'chen', 'user')"))
    monkeypatch.setattr(settings, "jwt_secret", SECRET)
    monkeypatch.setattr(settings, "documents_dir", str(tmp_path / "upload"))
    for mod in ("app.core.db", "app.core.identity", "app.core.session_repo"):
        monkeypatch.setattr(f"{mod}.get_engine", lambda: engine)

    out = tmp_path / "upload" / "dev" / "_out"
    out.mkdir(parents=True)
    # 120 行 csv
    with (out / f"{EID}.csv").open("w", encoding="utf-8-sig", newline="") as h:
        w = csv.writer(h)
        w.writerow(["门店", "销售金额"])
        for i in range(120):
            w.writerow([f"门店{i % 7}", f"{i + 1}.50"])
    # xlsx 两个工作表
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "明细"
    ws.append(["下单时间", "销售金额"])
    for i in range(75):
        ws.append([f"2026-01-{(i % 28) + 1:02d}", i + 1])
    wb.create_sheet("汇总", 1).append(["月份", "合计"])
    wb.save(str(out / f"{EID}.xlsx"))
    (out / "w-0123456789abcdef.md").write_text("# 总结\n\n正文", encoding="utf-8")

    import jwt as pyjwt

    token = pyjwt.encode({"sub": "EMP001", "tv": 0}, SECRET, algorithm="HS256")
    chen = pyjwt.encode({"sub": "EMP002", "tv": 0}, SECRET, algorithm="HS256")
    return TestClient(app), {"Authorization": f"Bearer {token}"}, {"Authorization": f"Bearer {chen}"}


def test_table_requires_auth(client):
    c, _, _ = client
    assert c.get(f"/api/v1/documents/table?name=dev/_out/{EID}.csv").status_code == 401


def test_table_csv_pagination(client):
    c, auth, _ = client
    r = c.get(f"/api/v1/documents/table?name=dev/_out/{EID}.csv&offset=0&limit=50", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert data["columns"] == ["门店", "销售金额"]
    assert data["total"] == 120 and len(data["rows"]) == 50 and data["sheet"] is None
    assert data["rows"][0] == ["门店0", "1.50"]

    r2 = c.get(f"/api/v1/documents/table?name=dev/_out/{EID}.csv&offset=100&limit=50", headers=auth)
    data2 = r2.json()
    assert len(data2["rows"]) == 20  # 最后一页不满
    assert data2["rows"][-1] == ["门店0", "120.50"]  # 第 119 行：119%7=0


def test_table_xlsx_sheets_and_paging(client):
    c, auth, _ = client
    r = c.get(f"/api/v1/documents/table?name=dev/_out/{EID}.xlsx", headers=auth)
    data = r.json()
    assert data["sheets"] == ["明细", "汇总"]
    assert data["sheet"] == "明细" and data["total"] == 75
    # 切工作表
    r2 = c.get(f"/api/v1/documents/table?name=dev/_out/{EID}.xlsx&sheet=汇总", headers=auth)
    assert r2.json()["sheet"] == "汇总"
    # 不存在的工作表如实报错
    assert c.get(f"/api/v1/documents/table?name=dev/_out/{EID}.xlsx&sheet=不存在", headers=auth).status_code == 400


def test_table_rejects_non_table_file(client):
    c, auth, _ = client
    r = c.get("/api/v1/documents/table?name=dev/_out/w-0123456789abcdef.md", headers=auth)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "NOT_A_TABLE"


def test_table_owner_isolation(client):
    """chen 预览不了 dev 目录里的文件（路径按用户隔离）。"""
    c, _, chen = client
    assert c.get(f"/api/v1/documents/table?name=dev/_out/{EID}.csv", headers=chen).status_code == 400


def test_download_returns_raw_file(client):
    c, auth, _ = client
    r = c.get(f"/api/v1/documents/content?name=dev/_out/{EID}.csv&download=true", headers=auth)
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")
    # 是原始文件（120 行都在），不是 20 行抽取版
    body = r.text
    assert body.count("\n") >= 121 and "119.50" in body
    assert r.headers["content-type"].startswith("text/csv")


def test_download_xlsx_bytes(client):
    c, auth, _ = client
    r = c.get(f"/api/v1/documents/content?name=dev/_out/{EID}.xlsx&download=true", headers=auth)
    assert r.status_code == 200
    assert r.content[:2] == b"PK"  # xlsx 是 zip 容器
