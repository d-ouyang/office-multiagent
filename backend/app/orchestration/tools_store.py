"""生成文件的落盘和落库。

字节在 data/upload/<用户名>/_out/，经 compose 挂到宿主机，重建镜像不会清掉。
asset 表只记编号、所属用户、相对路径和任务，不把文件内容塞进数据库。
"""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine


def new_output_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(8)}"


def output_file(base: Path, filename: str) -> Path:
    folder = (base / "_out").resolve()
    folder.mkdir(parents=True, exist_ok=True)
    target = (folder / filename).resolve()
    if not target.is_relative_to(folder):
        raise ValueError("非法输出路径")
    return target


def record_asset(
    engine: Engine | None,
    *,
    asset_id: str,
    user_id: int | None,
    task_id: str | None,
    kind: str,
    name: str,
    rel_path: str,
) -> bool:
    """有数据库连接时写入 asset。没有连接（单测）则跳过，文件仍算生成成功。"""
    if engine is None:
        return False
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO asset (id, task_id, type, storage_url, user_id, name, rel_path) "
                "VALUES (:id, :task, :type, :url, :uid, :name, :path)"
            ),
            {
                "id": asset_id,
                "task": task_id,
                "type": kind,
                "url": rel_path,
                "uid": user_id,
                "name": name,
                "path": rel_path,
            },
        )
    return True


def finish_output(
    engine: Engine | None,
    target: Path,
    *,
    asset_id: str,
    user_id: int | None,
    task_id: str | None,
    kind: str,
    name: str,
    rel_path: str,
) -> bool:
    try:
        return record_asset(
            engine,
            asset_id=asset_id,
            user_id=user_id,
            task_id=task_id,
            kind=kind,
            name=name,
            rel_path=rel_path,
        )
    except Exception:
        target.unlink(missing_ok=True)
        raise
