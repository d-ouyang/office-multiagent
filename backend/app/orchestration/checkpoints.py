"""p5.4：checkpointer 共享与持久化。

⚠️ **接 sqlite 前必读的命名注意**（2026-11-01 在 langgraph 1.2.16 上实测，不是猜测）：

1. **memory 侧的两个名字是同一个东西，不是新旧两套 API。**
   `checkpoint/memory.py:34` 定义的正式类是 `class InMemorySaver`；
   同文件 `:634` 写着 `MemorySaver = InMemorySaver  # Kept for backwards compatibility`
   —— 即 `MemorySaver` 只是**向后兼容别名**，两者 `is` 同一对象，
   且导入时**不会触发 DeprecationWarning**（用 `-W error::DeprecationWarning` 验证过）。
   => 所以本文件继续用 `MemorySaver` 没有错、没有警告、也没有迁移负担；
      但**看官方新文档时看到 `InMemorySaver` 不要以为是需要适配的不兼容新 API**，
      它就是同一个类。别为此做无意义的改名改造。

2. **sqlite 侧命名与 memory 侧不对称，这才是真正要小心的坑。**
   ```python
   from langgraph.checkpoint.sqlite import SqliteSaver          # 同步：本项目 graph.invoke 用它
   from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # 异步：只有换 astream 才需要
   ```
   这里**没有** `InSqliteSaver` 这种带 `In` 前缀的变体，不要按 memory 的规律类推。
   本项目 `graph.invoke()` 是同步调用，因此 p5.4 用的是同步 `SqliteSaver` +
   `sqlite3.connect(..., check_same_thread=False)`（`/tasks` 在 worker 线程跑）。
   若将来把执行改为 `astream`，必须换成 `AsyncSqliteSaver`，同步版在事件循环里会阻塞。

3. **postgres 侧**：`PostgresSaver` / `AsyncPostgresSaver`。
   sqlite 不适合多副本共享（backend 多实例部署时各自一个文件，等于各写各的），
   届时才需要评估 postgres。

--- 以下为模块说明 ---

此前 `run_task` 每次 `MemorySaver()` 新建一个实例：
  · 存档随本次调用结束即失去引用，**同进程内后续调用也找不回**；
  · 进程重启（`restart backend`）后所有挂起任务的存档全部丢失；
  · 因此续跑只能退化为「按原请求从头重跑」（routes.py 的 retry_of 方案），
    已完成的节点会重复执行、重复计费。

本模块按 `settings.checkpointer_backend` 提供 checkpointer：

- `memory`（缺省）：**严格保持现状**——每次调用返回新的 `MemorySaver`，
  行为与 p5.4 之前完全一致，不做任何隐式共享（避免影响既有测试与线上语义）。
- `sqlite`：进程级共享一个 `SqliteSaver`，落盘到 `checkpoint_sqlite_path`，
  跨调用、跨进程重启都能按 `thread_id` 找回存档。

线程安全：`/tasks` 在 worker 线程里跑（不是 FastAPI 事件循环线程），
所以 sqlite 连接必须 `check_same_thread=False`，创建过程用锁保护。
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from typing import Any

from ..core.config import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_sqlite_saver: Any | None = None
_sqlite_conn: sqlite3.Connection | None = None


def get_checkpointer() -> Any:
    """按配置返回 checkpointer。

    memory：每次新建（与历史行为一致）；sqlite：进程级共享单例。
    """
    backend = (settings.checkpointer_backend or "memory").strip().lower()
    if backend == "sqlite":
        return _shared_sqlite_saver()
    if backend != "memory":
        # fail-closed：配置写错不能静默落到某个后端，直接暴露
        raise ValueError(f"未知 checkpointer_backend={backend!r}，仅支持 memory | sqlite")
    # 注意：MemorySaver 与 InMemorySaver 是同一个类（前者为兼容别名，见模块头 §1）。
    # 这里沿用旧名不产生警告，也不影响后续接 sqlite——不要为此改名。
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()


def _shared_sqlite_saver() -> Any:
    global _sqlite_saver, _sqlite_conn
    with _lock:
        if _sqlite_saver is None:
            from langgraph.checkpoint.sqlite import SqliteSaver

            path = settings.checkpoint_sqlite_path
            directory = os.path.dirname(os.path.abspath(path))
            os.makedirs(directory, exist_ok=True)
            _sqlite_conn = sqlite3.connect(path, check_same_thread=False)
            _sqlite_saver = SqliteSaver(_sqlite_conn)
            logger.info("checkpointer 使用 sqlite 持久化：%s", path)
        return _sqlite_saver


def reset_checkpointer_for_tests() -> None:
    """测试专用：关掉共享连接并清空单例，避免用例之间互相看到存档。"""
    global _sqlite_saver, _sqlite_conn
    with _lock:
        if _sqlite_conn is not None:
            _sqlite_conn.close()
        _sqlite_conn = None
        _sqlite_saver = None
