# office-multiagent · 多 Agent 企业级智能办公助手

基于 `智能办公助手-多Agent系统设计方案-总结.md` 的多 Agent 办公助手。**Docker 优先**：前后端、数据库全部容器联动，不在本地从零手写前后端。

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | nginx 容器，反代 `/api` → backend（状态页 + 后续 Agent 可视化） |
| 中间层 | 阶段2 起加 NestJS 网关容器（认证 / 上传 / NDJSON 透传） |
| 编排后端 | Python 3.13 + FastAPI + LangGraph（规划器 / 路由 / Agent 编排，NDJSON 流） |
| 数据 | MySQL（真相源）/ Redis（broker+缓存）/ Chroma（向量，可复用共享实例） |

> 模型全部**云端**（硅基流动 / DeepSeek key 由用户持有），无本地部署；大模型列表与中间小模型（embedding/reranker/decision）均走 `backend/config/models.yaml` 配置，不硬编码。

## 本地启动（Docker）

```bash
cp .env.example .env          # 按需改密码 / 填模型 key
docker compose up -d --build  # 首次拉镜像+构建较重，按立项纪律【不自动跑】，请本地显式执行
```

启动后访问：
- 前端：http://localhost:8080
- 后端 API 文档：http://localhost:8000/docs
- 健康检查：`curl http://localhost:8000/api/v1/health`
- 模型列表：`curl http://localhost:8000/api/v1/models`

## 远程部署（腾讯云轻量 4C4G，沙箱可直连）

与 RAG 同机：**中间件共享、容器独立**。沙箱经 SSH 直连服务器（`ssh -o BatchMode=yes ubuntu@42.192.111.82`），部署不需要你手动复制命令。详见 `docs/PLAN-1.0.0.md` Phase 7。

## 版本纪律

- 版本号 `vX.Y.Z-pN.M`（p 段对应 PLAN 任务编号）。
- 每步：总结（`docs/iterations/`）+ 打 tag + release（`docs/RELEASES.md`）+ testcase。
- 老 tag 永不重打；涉及数据库清洗/删除或重耗时操作默认不自动跑。

详见 [`docs/PLAN-1.0.0.md`](docs/PLAN-1.0.0.md) 与 [`docs/RELEASES.md`](docs/RELEASES.md)。
