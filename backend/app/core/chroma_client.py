"""Chroma 客户端 + 探活。

chromadb 较重，import 放到函数内（懒加载），这样 app 导入 / 单测
无需安装 chromadb；只有真正探活 chroma 时才 import。
"""
from .config import settings


def ping_chroma() -> tuple[bool, str | None]:
    try:
        import chromadb  # 懒加载，避免重依赖拖累导入/测试

        c = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
        c.heartbeat()
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, str(e)
