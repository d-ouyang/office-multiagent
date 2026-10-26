"""MySQL 连接（SQLAlchemy 引擎 + 探活）。

真相源分工（设计文档 §11.5 / rag 铁律）：用户/会话/文档元数据 → MySQL；
这里只建引擎与 ping，不做 SELECT/DELETE 之类的业务操作，避免误清数据。

连接层加固（p1.2a）：引擎懒创建（get_engine），连接池参数走配置；
pool_pre_ping 让每次借用前探测，DB 短暂重启后能自愈而不抛 stale connection。
"""
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import settings

DATABASE_URL = (
    f"mysql+pymysql://{settings.mysql_user}:{settings.mysql_password}"
    f"@{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}?charset=utf8mb4"
)

_engine: Engine | None = None


def get_engine() -> Engine:
    """懒创建引擎（依赖注入入口）。后续仓储层从这里拿连接。"""
    global _engine
    if _engine is None:
        # p6.45：强制本连接会话时区为 UTC——共享 MySQL（rag-mysql）全局 time_zone=+08:00，
        # CURRENT_TIMESTAMP 默认值会写北京墙钟，而 _iso_utc 按"库里存的是 UTC"打 Z 标，
        # 两者叠加 = 前端显示比实际快 8 小时。这里把会话时区钉死 UTC，全链路口径统一。
        connect_args = (
            {"init_command": "SET time_zone = '+00:00'"} if DATABASE_URL.startswith("mysql") else {}
        )
        _engine = create_engine(
            DATABASE_URL,
            pool_size=settings.mysql_pool_size,
            max_overflow=settings.mysql_max_overflow,
            pool_timeout=settings.mysql_pool_timeout,
            pool_pre_ping=True,      # 每次借用前探测，抗 DB 瞬断
            pool_recycle=3600,       # 定时回收，避免 MySQL wait_timeout 打死空闲连接
            connect_args=connect_args,
        )
    return _engine


def ping_mysql() -> tuple[bool, str | None]:
    """返回 (是否可达, 错误信息)。只读 SELECT 1，绝不写/删。"""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, None
    except Exception as e:  # noqa: BLE001 - 探活就是要吞异常给健康接口
        return False, str(e)
