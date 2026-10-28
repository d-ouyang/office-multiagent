"""Chroma 客户端 + 探活。

chromadb 较重，import 放到函数内（懒加载），这样 app 导入 / 单测
无需安装 chromadb；只有真正探活 chroma 时才 import。

v2.0.0-p2.6（生产 OOM 复盘）：HttpClient **必须复用**——此前每次 ping
新建 HttpClient 且从不关闭，底层 httpx 连接池（socket + 对象）随调用数
线性泄漏：/health 与 /admin/overview 每次请求各泄一个，一夜累积出
1013 个 socket + 1.8GB RSS，触发内核 OOM（见 docs/RELEASES p2.4/p2.6）。
改为模块级单例 + 锁保护；探活失败时丢弃旧实例下次重建（自愈）。
"""
import threading

from .config import settings

_client = None
_client_lock = threading.Lock()


def _get_client():
    """复用单例 HttpClient；失败后置 None，下次调用重建（自愈）。"""
    global _client
    import chromadb  # 懒加载，避免重依赖拖累导入/测试

    with _client_lock:
        if _client is None:
            _client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
        return _client


def _drop_client() -> None:
    global _client
    with _client_lock:
        _client = None


def ping_chroma() -> tuple[bool, str | None]:
    try:
        _get_client().heartbeat()
        return True, None
    except Exception as e:  # noqa: BLE001
        _drop_client()  # 坏实例（连接池挂死等）下次重建，不让单例变成永久故障
        return False, str(e)
