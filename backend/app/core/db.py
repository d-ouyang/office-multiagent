"""MySQL 连接（SQLAlchemy 引擎 + 探活）。

真相源分工（设计文档 §11.5 / rag 铁律）：用户/会话/文档元数据 → MySQL；
这里只建引擎与 ping，不做 SELECT/DELETE 之类的业务操作，避免误清数据。
"""
from sqlalchemy import create_engine, text

from .config import settings

DATABASE_URL = (
    f"mysql+pymysql://{settings.mysql_user}:{settings.mysql_password}"
    f"@{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}?charset=utf8mb4"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)


def ping_mysql() -> tuple[bool, str | None]:
    """返回 (是否可达, 错误信息)。只读 SELECT 1，绝不写/删。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, None
    except Exception as e:  # noqa: BLE001 - 探活就是要吞异常给健康接口
        return False, str(e)
