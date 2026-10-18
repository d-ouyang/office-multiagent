"""FastAPI 应用入口（核心骨架）。

暴露：
  GET  /                          → 服务信息
  GET  /api/v1/health            → 联动探测 MySQL / Redis / Chroma
  GET  /api/v1/models            → 对话可见模型注册表（§十七.1）
  GET  /api/v1/internal/auth/ping → 内部调用鉴权自检（X-Internal-Token，fail-closed）
后续阶段（见 docs/PLAN-1.0.0.md）在此挂载 Planner / Router / Agent 编排、NDJSON 流、网关等。
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.routes import router
from .core.logging import CorrelationMiddleware, setup_logging
from .core.startup import warmup_connections

setup_logging()
logger = logging.getLogger("startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动期预热三件套连接（p1.2a）：未全绿则降级运行，不杀进程。"""
    report = warmup_connections()
    required_ok = report["mysql"]["ok"] and report["redis"]["ok"]
    if required_ok:
        logger.info("启动探活全绿 | %s", report)
    else:
        logger.error(
            "启动探活未全绿，降级运行（/health 暴露，逐请求自愈重连）| %s", report
        )
    yield


app = FastAPI(title="office-multiagent", version="1.0.0-p4.1", lifespan=lifespan)

app.add_middleware(CorrelationMiddleware)
app.include_router(router, prefix="/api/v1")


@app.get("/")
def root():
    return {"service": "office-multiagent", "docs": "/docs", "health": "/api/v1/health"}
