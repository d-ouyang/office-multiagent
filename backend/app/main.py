"""FastAPI 应用入口（核心骨架）。

暴露：
  GET  /                          → 服务信息
  GET  /api/v1/health            → 联动探测 MySQL / Redis / Chroma
  GET  /api/v1/models            → 对话可见模型注册表（§十七.1）
  GET  /api/v1/internal/auth/ping → 内部调用鉴权自检（X-Internal-Token，fail-closed）
后续阶段（见 docs/PLAN-1.0.0.md）在此挂载 Planner / Router / Agent 编排、NDJSON 流、网关等。
"""
from fastapi import FastAPI

from .api.routes import router
from .core.logging import CorrelationMiddleware, setup_logging

setup_logging()

app = FastAPI(title="office-multiagent", version="1.0.0-p1.1")

app.add_middleware(CorrelationMiddleware)
app.include_router(router, prefix="/api/v1")


@app.get("/")
def root():
    return {"service": "office-multiagent", "docs": "/docs", "health": "/api/v1/health"}
