"""p6.12：会话列表 updated_at + 随消息附件（校验/prompt 注入）测试。

不连真库不花钱：SessionRepo 用 sqlite 内存库；附件校验用 tmp_path 假文档目录。
"""
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.api.routes import _compose_task_text, _validate_attachment, _validate_attachments
from app.core.config import settings
from app.core.session_repo import SessionRepo


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with eng.begin() as c:
        c.execute(text("CREATE TABLE session (id TEXT PRIMARY KEY, user_id INTEGER, model TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        c.execute(text("CREATE TABLE message (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content TEXT, trace TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
    return eng


def _add_session(eng, sid: str, user_id: int = 1, created_at: str = "2026-01-01 08:00:00"):
    with eng.begin() as c:
        c.execute(
            text("INSERT INTO session (id, user_id, created_at) VALUES (:i, :u, :t)"),
            {"i": sid, "u": user_id, "t": created_at},
        )


def _add_message(eng, sid: str, content: str, created_at: str, role: str = "user"):
    with eng.begin() as c:
        c.execute(
            text("INSERT INTO message (session_id, role, content, created_at) VALUES (:s, :r, :c, :t)"),
            {"s": sid, "r": role, "c": content, "t": created_at},
        )


# ---------- list_sessions：updated_at 语义 ----------

def test_list_sessions_updated_at_is_last_message_time(engine):
    """updated_at = 最后一条消息时间（不是加载时刻）；按 updated_at 倒序。"""
    _add_session(engine, "s-old", created_at="2026-01-01 08:00:00")
    _add_session(engine, "s-new", created_at="2026-01-01 09:00:00")
    # s-old 后来被追问过：最后消息 10:00（晚于 s-new 的创建）
    _add_message(engine, "s-old", "第一问", "2026-01-01 08:05:00")
    _add_message(engine, "s-old", "追问", "2026-01-01 10:00:00")

    out = SessionRepo(engine).list_sessions(1)
    assert [s["session_id"] for s in out] == ["s-old", "s-new"]  # 按最后活跃排
    assert out[0]["updated_at"] == "2026-01-01T10:00:00Z"  # 最后一条消息时间（str 分支不带微秒，带 UTC 标记）
    assert out[1]["updated_at"] == "2026-01-01T09:00:00Z"  # 无消息回落 created_at


def test_list_sessions_no_message_falls_back_to_created_at(engine):
    _add_session(engine, "s-empty", created_at="2026-02-03 12:30:00")
    out = SessionRepo(engine).list_sessions(1)
    assert out[0]["updated_at"] == "2026-02-03T12:30:00Z"


# ---------- _iso_utc：时间字段带 UTC 标记（p6.12c 修差 8 小时） ----------

def test_iso_utc_variants():
    from app.core.session_repo import _iso_utc
    from datetime import datetime as _dt

    assert _iso_utc(_dt(2026, 10, 21, 13, 40, 13, 380547)) == "2026-10-21T13:40:13.380547Z"  # MySQL datetime
    assert _iso_utc("2026-01-01 08:00:00") == "2026-01-01T08:00:00Z"  # SQLite str
    assert _iso_utc("2026-01-01T08:00:00Z") == "2026-01-01T08:00:00Z"  # 已带标记不重复
    assert _iso_utc(None) == "" and _iso_utc("") == ""


# ---------- 附件校验（fail-closed） ----------

@pytest.fixture
def doc_dir(tmp_path, monkeypatch):
    base = tmp_path / "upload"
    (base / "dev").mkdir(parents=True)
    (base / "dev" / "报告.md").write_text("内容", encoding="utf-8")
    (base / "other").mkdir()
    (base / "other" / "secret.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(settings, "documents_dir", str(base))
    return base


def test_validate_attachments_ok_own_dir(doc_dir):
    out = _validate_attachments(["dev/报告.md", "报告.md"], "dev")
    assert out == ["dev/报告.md", "dev/报告.md"]  # basename 拍平到本人目录


def test_validate_attachments_rejects_traversal(doc_dir):
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        _validate_attachments(["../other/secret.txt"], "dev")


def test_validate_attachments_rejects_other_users_file(doc_dir):
    """越权引用他人目录 → 拍平后 dev 目录内不存在 → 400。"""
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        _validate_attachments(["other/secret.txt"], "dev")


def test_validate_attachments_rejects_missing_file(doc_dir):
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        _validate_attachments(["dev/不存在.md"], "dev")


def test_validate_attachments_empty_returns_empty(doc_dir):
    assert _validate_attachments(None, "dev") == []
    assert _validate_attachments([], "dev") == []


def test_single_attachment_helper(doc_dir):
    assert _validate_attachment("dev/报告.md", "dev") == ["dev/报告.md"]
    assert _validate_attachment(None, "dev") == []


# ---------- prompt 前缀注入 ----------

def test_compose_task_text_no_attachments_unchanged():
    assert _compose_task_text("查年假制度", []) == "查年假制度"


def test_compose_task_text_with_attachments_prefix():
    out = _compose_task_text("总结一下", ["dev/a.md", "dev/b.pdf"])
    assert out.startswith("[用户随消息上传了这些文件，已放在当前用户的上传目录：a.md、b.pdf。")
    assert "file_name 只填文件名" in out
    assert "read_document" in out
    assert out.endswith("总结一下")  # 原文在后，未被改写
