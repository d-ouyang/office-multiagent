# office-multiagent · 多 Agent 企业级智能办公助手

> 基于 `智能办公助手-多Agent系统设计方案-总结.md` 落地的新项目。
> 立项原则（见 docs/PLAN-1.0.0.md）：**Docker 优先**——前后端、数据库全部以容器方式联动，不在本地从零手写前后端；
> **版本纪律**：每步完成写总结、每阶段成功打 tag、每次打 tag 出 release 文档、每步有 testcase。

## 目录结构

```
office-multiagent/
├── docker-compose.yml        # 串起 frontend / backend / mysql / redis / chroma
├── backend/                  # FastAPI + LangGraph 编排后端（容器化）
│   ├── Dockerfile
│   ├── requirements.txt      # 来自主仓已验证清单（pip dry-run 零冲突）
│   └── app/                  # 应用代码（当前为联动脚手架）
├── frontend/                 # 前端容器（nginx 反代 /api → backend）
│   ├── Dockerfile
│   └── public/index.html     # 状态页（调 /api/v1/health）
├── db/
│   └── init.sql              # MySQL 建表（session/task/wallet/token_ledger/model_pool…）
├── docs/
│   ├── PLAN-1.0.0.md         # 可执行计划（本文件是源头）
│   ├── RELEASES.md           # 每次打 tag 的 release 文档
│   └── iterations/           # 每步完成总结（vX.Y.Z-pN.M-<slug>.md）
└── tests/                    # 见 backend/tests（随镜像跑 pytest）
```

## 本地启动（Docker）

```bash
cp .env.example .env          # 按需改密码
docker compose up -d --build  # 首次会拉镜像 + 构建，稍慢
# 前端 http://localhost:8080  /  后端 http://localhost:8000/docs
curl http://localhost:8000/api/v1/health
```

> ⚠️ 首次 `docker compose up` 会拉取 MySQL/Redis/Chroma 镜像并构建后端（装 requirements，含 chromadb 较重），
> 属「耗时操作」，按立项纪律**不自动跑**——请本地显式执行，或让我在远程服务器经沙箱 SSH 跑。

## 远程部署（腾讯云轻量 4C4G，沙箱可直连）

```bash
# 沙箱内（无需你手动复制命令）：
ssh -o BatchMode=yes ubuntu@42.192.111.82 'mkdir -p /opt/office && cd /opt/office && git pull'
# 或直接把本仓库推到服务器后 docker compose up
```
服务器现状与 RAG 同机，故**中间件共享、容器独立**（详见设计文档 §12.3、§12.4）。

## 版本纪律

- 版本号：`vX.Y.Z-pN.M`（p 段对应 PLAN 任务编号，半项加字母后缀）。
- 老 tag 永不重打；打前 `git tag | grep 'pN\.M'` 查占用。
- 每步完成 → `docs/iterations/vX.Y.Z-pN.M-<slug>.md` 总结。
- 每阶段成功 → `git tag` + `docs/RELEASES.md` 加一条。
- 每步有 testcase（`pytest`，DB 清理/删除类操作默认 skip，防误跑）。
