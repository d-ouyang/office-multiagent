# PLAN-1.0.0 · 多 Agent 企业级智能办公助手（可执行计划）

> 本计划派生自 `../智能办公助手-多Agent系统设计方案-总结.md`（以下简称**设计文档**）。  
> 设计文档回答"做什么 / 为什么"；本文件回答"按什么顺序做 / 每步交付什么 / 怎么验收 / 怎么打点留痕"。  
> 版本：`v1.0.0`（Plan 文档自身随里程碑迭代，命名 `PLAN-vX.Y.Z.md`）。

---

## 1. 立项原则（来自用户 7 条指令，必须全程遵守）

1. **Docker 优先（点7）**：前后端 + 数据库全部以容器方式联动，**不在本地从零手写前后端**；用 `docker-compose` 把 frontend / backend / mysql / redis / chroma 串起来。
2. **库全升稳定版 + venv + 国内镜像（点3）**：依赖用已验证的 `backend/requirements.txt`（`pip install --dry-run` 零冲突）；部署走 venv，服务器无 clashx，安装走腾讯云/阿里镜像。
3. **版本纪律（点4）**：每步完成写总结 → `docs/iterations/vX.Y.Z-pN.M-<slug>.md`；每阶段成功打 tag → `git tag`；每次打 tag 出 release → `docs/RELEASES.md`；每步有 testcase。
4. **谨慎自动跑（点5）**：涉及数据库清洗/删除、或重耗时操作（如 `docker compose up` 首次拉镜像构建、全量测试、迁移），**默认不自动跑**，需显式执行或经确认。
5. **远程直连（点6）**：沙箱可经 SSH 直连远程服务器（`ssh -o BatchMode=yes ubuntu@42.192.111.82`，私钥 `~/.ssh/id_ed25519`），部署/验证不需用户手动复制命令。
6. **共享中间件 + 瘦后端（设计文档 §12.3/§12.4）**：与 qa(RAG) 同机时，容器独立、中间件（MySQL/Redis/Chroma）共享；当前**不升配**，4C4G 顶住。
7. **需求借鉴不照搬（设计文档 §十一）**：RAG 的 65+ 坑只借鉴"要做什么"，实现按本架构（LangGraph 多 Agent、多状态副本）重新设计。

---

## 2. 技术栈（Docker 化映射）

| 层   | 容器 / 技术                                           | 说明                                           |
| --- | ------------------------------------------------- | -------------------------------------------- |
| 前端  | `frontend`（nginx:alpine，反代 `/api` → backend）      | 状态页 + 后续 Agent 执行可视化（§十五）                    |
| 中间层 | 阶段2 起加 `gateway`（NestJS 容器）                       | 当前由 backend 直出 NDJSON，网关后续补                  |
| 编排  | `backend`（python:3.13-slim + FastAPI + LangGraph） | 规划器/路由/Agent 编排、NDJSON 流                     |
| 数据  | `mysql` / `redis` / `chroma` 容器                   | MySQL 真相源；Redis broker/缓存；Chroma 向量（可复用共享实例） |
| 边缘  | 服务器侧 Caddy（阶段7）                                   | 反代 + TLS + 多 site（§12.3）                     |

> **NDJSON 不是 SSE**（设计文档 §12.1）：异构事件逐行 JSON，Caddy/nginx 必须 `proxy_buffering off` + 放长 `proxy_read_timeout`，前端 `fetch`+`ReadableStream` 逐行解析。

---

## 3. 版本纪律细则（点4）

- **Tag 格式**：`vX.Y.Z-pN.M`（`p` 段对应本计划任务编号，半项加字母后缀，如 `p3.1` / `p3.1a`）。
- **老 tag 永不重打**：打前 `git tag | grep 'pN\.M'` 查占用；判新旧看 `git log` 不看编号。
- **每步完成五件事**：① `docs/iterations/vX.Y.Z-pN.M-<slug>.md`（六节，§3 否掉的方案最值钱）② `docs/RELEASES.md` 加对外段 ③ `git commit` ④ `git tag` ⑤ 更新本计划进度总览表。
- **测试**：每步有 `backend/tests/` 对应 testcase；集成类默认 `skip`（需 `OFFICE_INTEGRATION=1` + `docker compose up`）。

---

## 4. 分阶段执行计划

> 每阶段标注：目标 / 范围（做·不做）/ 任务 / 交付物 / 测试 / Tag。

### Phase 0 · 脚手架 + Docker 联动  【已完成 → v1.0.0-p0.1】

- **目标**：把"前后端+DB 容器联动"跑通（结构层面），建立版本纪律骨架。
- **范围**：做 = 目录结构、compose、backend/frontend 脚手架、`db/init.sql`、tests、本计划、requirements 落地、git 初始化 + tag + release。不做 = 任何 Agent 业务代码。
- **交付物**：`docker-compose.yml`、backend（/health 联动探测）、frontend（状态页）、`db/init.sql`、本文件、`requirements.txt`。
- **测试**：`pytest backend/tests/test_smoke.py`（免服务，验证 app 导入与 /health 结构）。集成测试 `test_health.py` 默认 skip。
- **Tag**：`v1.0.0-p0.1`。

### Phase 1 · 后端核心骨架  【v1.0.0-p1.1（骨架前置） → p1.2】

- **目标**：把"联动"从脚手架变成可扩展内核——配置固化、三件套连接、鉴权 stub、模型注册表接口、日志与可观测性。
- **v1.0.0-p1.1（本迭代已交付）**：
  - ① 配置固化：`core/config.py` 增 `log_level`/`log_format`/`jwt_secret`/`internal_shared_secret`/`models_config`/云端 key 字段。
  - ② 鉴权 stub：`core/internal_auth.py`（`X-Internal-Token` + hmac 恒定时间比对，fail-closed，对应 RAG internal-auth.client.ts）；`/api/v1/internal/auth/ping` 受保护路由 + 测试。
  - ③ 模型注册表接口：`config/models.yaml`（配置驱动，对话大模型 + 逻辑小模型分列）+ `core/model_registry.py` + `/api/v1/models`（§十七.1 字段，按池过滤）。
  - ④ 日志与可观测性：`core/logging.py`（JSON 行 + `CorrelationMiddleware` + `log_agent_step`/`log_token_audit`/`log_duration`）+ 设计文档 §十八。
  - **不做**：Planner/Router、真实 Agent 逻辑、NDJSON 封装、alembic 迁移基线（留到 p1.2）。
  - **测试**：`test_models.py`（对话列表只含 in_dialogue、池过滤、逻辑小模型不泄漏）、`test_internal_auth.py`（token 正确放行/缺省401/fail-closed）、`test_logging.py`（JSON 摊平 extra、辅助函数可用）。
  - **Tag**：`v1.0.0-p1.1` + release。
- **v1.0.0-p1.2a（已完成 · 任务 1）**：连接层加固——`db.py`/`redis_client.py` 改懒创建工厂 + 池/超时参数走配置；新增 `core/startup.py` 启动期线性退避预热三件套，mysql/redis 未就绪降级不杀进程（`main.py` lifespan）。测试 `test_connection.py`。
- **v1.0.0-p1.2b（已完成 · 任务 2）**：NDJSON 事件封装（§15.1）——`core/events.py`（`EventType`/`Event`/`EventSequence`/`RunEventEmitter` + orjson 序列化）+ `/api/v1/demo/stream` canned 序列。测试 `test_events.py`。
- **v1.0.0-p1.2c（已完成 · 任务 3）**：alembic 脚手架（`alembic.ini` + `migrations/env.py` 用 `DATABASE_URL` 覆盖）+ 基线迁移 `0001_initial_baseline`（镜像 init.sql 12 表 + 种子，幂等）+ 漂移护栏 `test_migrations.py`。**Phase 1 至此全部完成**。

### Phase 2 · 流式协议 + 中间层  【v1.0.0-p2.1a（网关）→ p2.1b（前端）】

- **目标**：NestJS 网关容器接 NDJSON 转发；前端执行可视化组件接入（折叠步骤条、§十五.2 优化）。
- **v1.0.0-p2.1a（已完成）**：`gateway` 容器——全局 `JwtAuthGuard`（passport-jwt，与后端 PyJWT 共用密钥）+ `@Public()` 白名单；`ProxyController` 把 `/api/v1/*` NDJSON 透传（不缓冲/不重排，守卫先于转发）；`InternalAuthClient` 用 `node:http` + `X-Internal-Token` 调后端内部探活；配置 fail-closed。frontend nginx `/api`→gateway。测试 `configuration.spec.ts` + `proxy.e2e.spec.ts`（真跑 9 passed）。
- **v1.0.0-p2.1b（待做）**：前端 `ToolCallsCollapse` 类组件（参考 `weight-loss-agent/src/components/ToolCallsCollapse.tsx`）+ NDJSON 流式 hook（§15.2 Worker/双层缓冲/虚拟滚动）。
- **Tag**：`v1.0.0-p2.1a` / `p2.1b`。

### Phase 3 · Planner + Router  【v1.0.0-p3.1 / p3.2】

- **目标**：复杂度判断 + 单/多 Agent 路由 + DAG 拆分（设计文档 §四.2/§四.3）。
- **任务**：① `Planner` 意图识别+复杂度打分；② `Router` 简单→单 Agent ReAct / 复杂→Orchestrator；③ DAG 拆分子任务；④ NDJSON 推 `status`/`thinking_delta`。
- **测试**：用固定用例断言路由结果（简单 vs 复杂）、DAG 依赖图正确。
- **Tag**：`v1.0.0-p3.1`（Router）/ `p3.2`（DAG）。

### Phase 4 · 多 Agent 协调 + 兜底 + 断点续跑  【v1.0.0-p4.1 / p4.2】

- **目标**：Orchestrator 调度、串行/并行汇总、工具异常兜底、checkpointer 断点续跑、token 硬上限（设计文档 §四.4/§四.5/§四.6、§十四）。
- **任务**：① Orchestrator 串行+并行后汇总；② 工具重试/降级/转人工（§四.5 表）；③ LangGraph checkpointer 持久化；④ 任务级 / 单 Agent `max_iterations` + 两段式 token 扣减（reserve/settle，原子 MySQL `UPDATE ... WHERE balance>=x`）；⑤ 中断 `paused_insufficient_quota` + 续跑（§十四.3）。
- **测试**：超时强制中止给阶段结论；余额不足→中断事件+续跑恢复；反向验证护栏（拆掉后断言转红，§11.6）。
- **Tag**：`v1.0.0-p4.1`（协调+兜底）/ `p4.2`（token 池+续跑）。

### Phase 5 · 办公能力补齐  【v1.0.0-p5.1 … p5.6】

- **目标**：数据分析/清洗/报表/可视化/图片还原/RAG 检索 Agent 逐个落地（设计文档 §五）。
- **RAG Agent 关键点**：把现有 qa 系统当**外部工具/Agent** 调（§12.3），不重写；本服务只新建轻量检索管线复用共享 Chroma。
- **测试**：每个 Agent 单测（pandas 算数用代码、不用 LLM，§九）；RAG 检索走外部端点 mock。
- **Tag**：按能力分 `p5.1`…`p5.6`。

### Phase 6 · Token 池 + 模型权限 + 前端精细化 + 上下文压缩  【v1.0.0-p6.1 / p6.2 / p6.3】

- **目标**：落地 §十三（开关作用域）、§十四（用户级模型切换+共享池+硬中断）、§十七（模型注册表面板 + 上下文压缩保语义）。
- **任务**：① 模型池/用户隔离数据模型 + 接口；② 实时两段式扣减 + 对账恒等式（§14.3）；③ 前端模型卡片（多模态✅/上下文窗口/思考流）+ 上下文超 85% 触发式分层压缩落 checkpoint（§17.2）。
- **测试**：并发子 Agent 不超额（两段式）；压缩后关键约束仍在（规则比对，非 LLM 自判）；开关越权被拒（fail-closed）。
- **Tag**：`v1.0.0-p6.1`（池+权限）/ `p6.2`（前端面板）/ `p6.3`（压缩）。

### Phase 7 · 部署到远程服务器  【v1.0.0-p7.1】

- **目标**：用点6 的 SSH 沙箱能力，把服务部署到 42.192.111.82（目录 `/opt/office`），共享中间件 + 瘦后端，Caddy 反代（§12.3）。
- **任务**：① 服务器建 `/opt/office` + 独立 compose + 独立端口 + 独立 `.env`；② 复用宿主 MySQL/Redis/Chroma（共享，不各起一份）；③ Caddy 加 `office.nianan.site`（或子路径）反代；④ 部署脚本（参考 RAG 的 `deploy.sh`）。
- **谨慎（点5）**：涉及服务器数据/迁移操作，先在沙箱 SSH 核实、不盲目跑清理；重耗时构建在服务器侧执行。
- **测试**：远程 `/api/v1/health` 全绿；前端可访问；CI/CD 走 GitHub Actions 自托管 runner（§12.2）。
- **Tag**：`v1.0.0-p7.1`。

---

## 5. 进度总览表（唯一权威进度）

| Phase | 内容                          | 状态    | Tag         |
| ----- | --------------------------- | ----- | ----------- |
| 0     | 脚手架 + Docker 联动             | ✅ 完成  | v1.0.0-p0.1 |
| 1     | 后端核心骨架（p1.1 / p1.2a / p1.2b / p1.2c） | ✅ 完成 | v1.0.0-p1.2c |
| 2     | 流式协议 + 中间层（p2.1a 网关完成，p2.1b 前端待做） | 🔶 p2.1a 完成 | v1.0.0-p2.1a |
| 3     | Planner + Router            | ⏳ 待开始 | —           |
| 4     | 多 Agent 协调 + 兜底 + 续跑        | ⏳ 待开始 | —           |
| 5     | 办公能力补齐                      | ⏳ 待开始 | —           |
| 6     | Token 池 + 模型权限 + 前端精细化 + 压缩 | ⏳ 待开始 | —           |
| 7     | 部署到远程服务器                    | ⏳ 待开始 | —           |

---

## 6. 环境搭建手册（执行用）

```bash
# 本地（Docker）
cd office-multiagent
cp .env.example .env
docker compose up -d --build     # ⚠️ 首次较重（拉镜像+构建），点5：显式执行，不自动跑
curl http://localhost:8000/api/v1/health
# 前端 http://localhost:8080

# 测试
pip install -i https://mirrors.cloud.tencent.com/pypi/simple fastapi pydantic-settings sqlalchemy redis httpx pytest
pytest backend/tests/test_smoke.py                 # 免服务
OFFICE_INTEGRATION=1 pytest backend/tests/test_health.py   # 需 compose up

# 远程（点6 沙箱直连，不需你复制命令）
ssh -o BatchMode=yes ubuntu@42.192.111.82 'cd /opt/office && git pull && docker compose up -d --build'
```
