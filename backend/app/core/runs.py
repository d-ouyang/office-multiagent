"""运行中任务的取消登记（p7.1 用户主动暂停）。

为什么需要：暂停 API 只能"通知"，真正停止要编排自己在步骤边界检查。用一个进程内
字典 task_id(run_id) → threading.Event 登记运行中的任务；暂停接口置位，ReAct 每一步
开始前、DAG 每个子任务开始前检查，命中即抛 `RunCancelled` 一路收尾。

范围：单实例部署足够（当前 compose 单 backend）。多副本需换 Redis 频道/共享存储，
届时只替换本模块实现，调用方不变（接口保持 register/finish/cancel/should_cancel）。
"""
from __future__ import annotations

import threading


class RunCancelled(Exception):
    """用户主动暂停（协作式取消）：在步骤边界抛出，由 run_task 统一收尾为 paused_user。"""


_RUNNING: dict[str, tuple[threading.Event, int | None]] = {}
_LOCK = threading.Lock()


def register(run_id: str, owner_id: int | None = None) -> threading.Event:
    """登记一个运行中的任务，返回它的取消事件；owner_id 用于暂停接口的归属校验
    （运行中的任务还没有 task 行，没法 join session 查 owner）。"""
    ev = threading.Event()
    with _LOCK:
        _RUNNING[run_id] = (ev, owner_id)
    return ev


def finish(run_id: str) -> None:
    """任务结束（正常/暂停/失败都算）→ 注销，防字典泄漏。"""
    with _LOCK:
        _RUNNING.pop(run_id, None)


def cancel(run_id: str, owner_id: int | None = None) -> bool:
    """请求暂停；任务不在运行中返回 False；owner_id 不匹配返回 False（不发信号）。"""
    with _LOCK:
        item = _RUNNING.get(run_id)
    if item is None:
        return False
    ev, owner = item
    if owner is not None and owner_id is not None and int(owner) != int(owner_id):
        return False
    ev.set()
    return True


def is_running(run_id: str) -> bool:
    with _LOCK:
        return run_id in _RUNNING


def should_cancel(ev: threading.Event | None):
    """给编排层用的检查器：无事件时永远 False（不传 = 不可暂停）。"""
    if ev is None:
        return lambda: False
    return ev.is_set
