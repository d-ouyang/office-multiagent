"""Redis 客户端 + 探活（仅 ping，不读写业务数据）。

连接层加固（p1.2a）：懒创建（get_redis），socket 超时走配置，
health_check_interval 让空闲连接被底层探测，抗 Redis 瞬断。
"""
import redis

from .config import settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """懒创建客户端（依赖注入入口）。"""
    global _client
    if _client is None:
        _client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            socket_timeout=settings.redis_socket_timeout,
            socket_connect_timeout=settings.redis_socket_connect_timeout,
            health_check_interval=settings.redis_health_check_interval,
            decode_responses=True,
        )
    return _client


def ping_redis() -> tuple[bool, str | None]:
    try:
        ok = get_redis().ping()
        return bool(ok), None
    except Exception as e:  # noqa: BLE001
        return False, str(e)
