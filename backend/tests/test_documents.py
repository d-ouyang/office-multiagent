"""文档上传测试（p6.6）——护栏：格式白名单/大小/traversal 拍平/用户目录隔离。"""
import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.main import app

SECRET = "test-jwt-secret-p66"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", SECRET)
    monkeypatch.setattr(settings, "documents_dir", str(tmp_path / "upload"))
    eng = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with eng.begin() as c:
        c.execute(text("CREATE TABLE user (id INTEGER PRIMARY KEY, employee_id TEXT, username TEXT, role TEXT, model_pool_id INTEGER, token_version INTEGER NOT NULL DEFAULT 0)"))
        c.execute(text("CREATE TABLE session (id TEXT PRIMARY KEY, user_id INTEGER, model TEXT, title TEXT, pinned INTEGER DEFAULT 0, pinned_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE message (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content TEXT, trace TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE wallet (user_id INTEGER PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0)"))
        c.execute(text("CREATE TABLE token_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, task_id TEXT, model TEXT, reserve INTEGER, settle INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE task (id TEXT PRIMARY KEY, session_id TEXT, complexity INTEGER, status TEXT DEFAULT 'pending', text TEXT, result TEXT, tokens_used INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("INSERT INTO user (id, employee_id, username, role) VALUES (1,'EMP001','dev','admin')"))
    for mod in ("app.core.db", "app.core.identity", "app.core.session_repo"):
        monkeypatch.setattr(f"{mod}.get_engine", lambda: eng)
    return TestClient(app)


def _token() -> str:
    return pyjwt.encode({"sub": "EMP001"}, SECRET, algorithm="HS256")


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token()}"}


def test_upload_ok(client, tmp_path):
    r = client.post(
        "/api/v1/documents",
        files={"file": ("handbook.md", b"# title\ncontent")},
        headers=_auth(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["file_name"] == "dev/handbook.md"  # 用户名子目录隔离
    assert body["size"] > 0
    assert (tmp_path / "upload" / "dev" / "handbook.md").read_bytes() == b"# title\ncontent"


def test_upload_traversal_filename_flattened(client, tmp_path):
    # ../../evil.md 被拍平成 basename，落点在用户目录内（路径穿越防护）
    r = client.post(
        "/api/v1/documents",
        files={"file": ("../../evil.md", b"x")},
        headers=_auth(),
    )
    assert r.status_code == 200
    assert r.json()["file_name"] == "dev/evil.md"
    assert (tmp_path / "upload" / "dev" / "evil.md").exists()
    assert not (tmp_path / "evil.md").exists()  # 没逃出去


def test_upload_and_preview_csv(client):
    r = client.post(
        "/api/v1/documents",
        files={"file": ("订单.csv", "地区,金额\n上海,12\n".encode())},
        headers=_auth(),
    )
    assert r.status_code == 200
    assert r.json()["file_name"] == "dev/订单.csv"
    preview = client.get(
        "/api/v1/documents/content", params={"name": "dev/订单.csv"}, headers=_auth()
    )
    assert preview.status_code == 200
    assert "列：地区、金额" in preview.text
    assert "上海 | 12" in preview.text


def test_upload_bad_format_rejected(client):
    r = client.post(
        "/api/v1/documents",
        files={"file": ("x.exe", b"MZ")},
        headers=_auth(),
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "BAD_FORMAT"


def test_upload_too_large_rejected(client):
    r = client.post(
        "/api/v1/documents",
        files={"file": ("big.md", b"x" * (10 * 1024 * 1024 + 1))},
        headers=_auth(),
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "TOO_LARGE"


def test_upload_empty_rejected(client):
    r = client.post("/api/v1/documents", files={"file": ("a.md", b"")}, headers=_auth())
    assert r.status_code == 400 and r.json()["detail"]["code"] == "EMPTY_FILE"


def test_upload_requires_token(client):
    r = client.post("/api/v1/documents", files={"file": ("a.md", b"x")})
    assert r.status_code == 401


def test_preview_own_file(client):
    client.post(
        "/api/v1/documents",
        files={"file": ("笔记.md", "# 标题\n正文".encode())},
        headers=_auth(),
    )
    r = client.get("/api/v1/documents/content", params={"name": "dev/笔记.md"}, headers=_auth())
    assert r.status_code == 200
    assert "正文" in r.text
    assert "inline" in r.headers["content-disposition"]


def test_preview_other_user_file_not_found(client, tmp_path):
    other = tmp_path / "upload" / "other"
    other.mkdir(parents=True)
    (other / "secret.md").write_text("机密", encoding="utf-8")
    r = client.get("/api/v1/documents/content", params={"name": "other/secret.md"}, headers=_auth())
    assert r.status_code == 400


def test_preview_generated_markdown(client, tmp_path):
    folder = tmp_path / "upload" / "dev" / "_out"
    folder.mkdir(parents=True)
    (folder / "w-0123456789abcdef.md").write_text("# 周报\n合计 12", encoding="utf-8")
    ok = client.get(
        "/api/v1/documents/content",
        params={"name": "_out/w-0123456789abcdef.md"},
        headers=_auth(),
    )
    assert ok.status_code == 200
    assert "合计 12" in ok.text
    escaped = client.get(
        "/api/v1/documents/content",
        params={"name": "_out/../secret.md"},
        headers=_auth(),
    )
    assert escaped.status_code == 400


def test_preview_requires_token(client):
    r = client.get("/api/v1/documents/content", params={"name": "a.md"})
    assert r.status_code == 401
