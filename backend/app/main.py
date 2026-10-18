"""FastAPI 应用入口（联动脚手架）。

当前只暴露：
  GET  /                        → 服务信息
  GET  /api/v1/health          → 联动探测 MySQL / Redis / Chroma
后续阶段（见 docs/PLAN-1.0.0.md）在此挂载 Planner / Router / Agent 编排、NDJSON 流、鉴权等。
"""
from fastapi import FastAPI

from .api.routes import router

app = FastAPI(title="office-multiagent", version="1.0.0-p0.1")

app.include_router(router, prefix="/api/v1")


@app.get("/")
def root():
    return {"service": "office-multiagent", "docs": "/docs", "health": "/api/v1/health"}
