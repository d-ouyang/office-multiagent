"""Redis 客户端 + 探活（仅 ping，不读写业务数据）。"""
import redis

from .config import settings

client = redis.Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    db=settings.redis_db,
    socket_connect_timeout=3,
    decode_responses=True,
)


def ping_redis() -> tuple[bool, str | None]:
    try:
        ok = client.ping()
        return bool(ok), None
    except Exception as e:  # noqa: BLE001
        return False, str(e)
