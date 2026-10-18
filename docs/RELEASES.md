# RELEASES · office-multiagent

> 每次打 tag 生成一条 release。纪律见 PLAN-1.0.0.md §3。
> 版本格式 `vX.Y.Z-pN.M`，老 tag 永不重打。

---

## v1.0.0-p2.1a — NestJS 网关容器：JWT 鉴权 + NDJSON 透传（2026-10-18）

**类型**：流式协议 + 中间层（Phase 2 前半）
**对应计划**：PLAN-1.0.0.md Phase 2 / v1.0.0-p2.1a
**Tag 提交**：见 `git show v1.0.0-p2.1a`

### 交付内容
- `gateway/` NestJS 10 容器：全局 `JwtAuthGuard`（passport-jwt，与后端 PyJWT 共用密钥）+ `@Public()` 白名单；`ProxyController` 把 `/api/v1/*` NDJSON 透传（`selfHandleResponse:false` 不缓冲、`Accept-Encoding:identity`、`fixRequestBody` 顺序纪律、代理注册为 Controller 使守卫先于转发）；`InternalAuthClient` 用 `node:http` + `X-Internal-Token` 调后端内部探活。
- 配置 fail-closed（生产缺 `GATEWAY_JWT_SECRET`/`INTERNAL_SHARED_SECRET` 启动失败）。
- 接线：`docker-compose.yml` 加 gateway 服务；frontend nginx `/api` → `gateway:3000`；`.env.example` 补全；`.gitignore` 屏蔽 Node 产物。

### 验证状态
- ✅ `tsc --noEmit` 通过。
- ✅ `jest`：9 passed（含 `proxy.e2e.spec.ts`：NDJSON 白名单透传有序、非白名单 401、有效 JWT 转发、内部 node:http ping 打通）。
- ✅ `docker compose config` 通过。
- ⏸️ 全栈 `docker compose up` 未自动跑（点5 谨慎）。

### 已知遗留
- 登录签发 / 网关身份头注入后端未做；未做网关限流；`package-lock.json` 未固化。

### 下一步
`v1.0.0-p2.1b`：前端执行可视化组件。

---

## v1.0.0-p1.2c — Alembic 迁移基线（2026-10-18，Phase 1 收口）

**类型**：后端核心骨架（Phase 1 / 任务 3）
**对应计划**：PLAN-1.0.0.md Phase 1 / v1.0.0-p1.2c
**Tag 提交**：见 `git show v1.0.0-p1.2c`

### 交付内容
- Alembic 脚手架：`backend/alembic.ini` + `migrations/env.py`（用 `core.db.DATABASE_URL` 覆盖 URL，单一真相源）+ `script.py.mako`。
- 基线迁移 `0001_initial_baseline.py`：镜像 `db/init.sql` 全部 12 表 + 种子（幂等 `CREATE TABLE IF NOT EXISTS` / `INSERT IGNORE`），downgrade 逆序 DROP。
- 漂移护栏 `test_migrations.py`：基线表集必须 == init.sql 表集；env 必须覆盖 URL；revision/down_revision 校验。

### 验证状态
- ✅ `pytest backend/tests`：30 passed / 3 skipped（新增 5 例）。
- ✅ `alembic history`（offline）：`<base> -> 0001_initial (head)`。
- ⏸️ 未对真实 MySQL 跑 upgrade（点5 谨慎）。

### 已知遗留
- 原生 DDL 基线；后续上 ORM 再考虑 autogenerate。迁移执行交 Phase 7 deploy 一次性跑，不在 app 启动自动跑（多副本 footgun）。

### 下一步
**Phase 2（p2.1）**：NestJS 网关 + 前端可视化。

---

## v1.0.0-p1.2b — NDJSON 事件封装（2026-10-18）

**类型**：后端核心骨架（Phase 1 / 任务 2）
**对应计划**：PLAN-1.0.0.md Phase 1 / v1.0.0-p1.2b
**Tag 提交**：见 `git show v1.0.0-p1.2b`

### 交付内容
- 新增 `core/events.py`：NDJSON 事件协议（§15.1/§15.3）——`EventType` 枚举、`Event` 信封（run_id/turn_id/seq/ts/data）、`EventSequence` 单调 seq、`RunEventEmitter` 类型化构造器、orjson 序列化（`encode_line`/`parse_line`，缺则回退标准 json）。
- 新增 `/api/v1/demo/stream`：canned NDJSON 序列，演示全协议类型，供前端/网关联调（Phase 3 前占位，不依赖外部服务）。

### 验证状态
- ✅ `pytest backend/tests`：25 passed / 3 skipped（新增 `test_events.py` 8 例）。
- ✅ 覆盖信封/seq 单调/构造器字段/round-trip/单行换行/未登记 type 从严/demo 端到端。
- ⏸️ 全栈实跑未自动跑（点5 谨慎）。

### 已知遗留
- `task_summary` 产物/来源为演示 dict，Phase 5/6 落库后回填；断点续流按 seq 续传留到 Phase 4。

### 下一步
`v1.0.0-p1.2c`：`db/init.sql` → alembic 迁移基线。

---

## v1.0.0-p1.2a — 连接层加固（2026-10-18）

**类型**：后端核心骨架（Phase 1 / 任务 1）
**对应计划**：PLAN-1.0.0.md Phase 1 / v1.0.0-p1.2a
**Tag 提交**：见 `git show v1.0.0-p1.2a`

### 交付内容
- 三件套客户端改**懒创建工厂**（`db.get_engine()` / `redis_client.get_redis()`），连接池 / 超时参数全部走配置（`mysql_pool_size` / `redis_socket_timeout` / `connect_max_retries` 等）。
- `pool_pre_ping` + `pool_recycle` / `health_check_interval`：DB/Redis 瞬断后逐请求自愈重连。
- 新增 `core/startup.py`：启动期线性退避预热三件套，`main.py` 加 `lifespan`；mysql/redis 未就绪**降级运行不杀进程**，由 `/health` 暴露。
- 顺带修 `log_duration` 用 `name` 撞 `LogRecord.name` 保留属性的 `KeyError`（改 `span` + 回归断言）。

### 验证状态
- ✅ `pytest backend/tests`：17 passed / 3 skipped（集成测试默认 skip）。
- ✅ 覆盖引擎/redis 单例与参数、重试语义、warmup 缺服务返回报告不抛。
- ⏸️ 全栈实跑未自动跑（点5 谨慎）。

### 已知遗留
- chroma 未加显式超时；全栈实跑 / 集成测试待显式执行。

### 下一步
`v1.0.0-p1.2b`：NDJSON 事件封装。

---

## v1.0.0-p1.1 — 后端核心骨架前置：鉴权 stub + 模型注册表 + 日志（2026-10-18）

**类型**：后端核心骨架（Phase 1 前半）
**对应计划**：PLAN-1.0.0.md Phase 1 / v1.0.0-p1.1
**Tag 提交**：见 `git show v1.0.0-p1.1`

### 交付内容
- **配置固化**（`core/config.py`）：新增 `log_level` / `log_format` / `jwt_secret` / `internal_shared_secret` / `models_config` / 云端模型 key 字段。
- **内部鉴权 stub**（`core/internal_auth.py`）：`X-Internal-Token` + hmac 恒定时间比对，fail-closed；对应 RAG `internal-auth.client.ts`。`/api/v1/internal/auth/ping` 受保护路由。
- **模型注册表（配置驱动）**：`backend/config/models.yaml`（对话大模型 + 逻辑小模型分列，全云端、不硬编码）+ `core/model_registry.py` + `/api/v1/models`（§十七.1 字段，按模型池过滤）。
- **日志与可观测性**（`core/logging.py`）：JSON 行日志 + `CorrelationMiddleware`（请求链路 correlation_id）+ `log_agent_step` / `log_token_audit` / `log_duration` 语义化辅助；设计文档新增 §十八。
- **README 精简**（用户点2）、`.env.example` 补全、GitHub 远端仓库建立并推送。

### 验证状态
- ✅ `pytest backend/tests/test_models.py`：对话列表只含 `in_dialogue` 模型、池过滤生效、逻辑小模型不泄漏。
- ✅ `pytest backend/tests/test_internal_auth.py`：token 正确放行 / 缺省 401 / fail-closed。
- ✅ `pytest backend/tests/test_logging.py`：JSON 摊平 extra、辅助函数可用。
- ✅ `pytest backend/tests/test_smoke.py`：app 导入与 /health 结构（app 导入保持轻量，pyyaml 懒加载）。
- ⏸️ 全栈实跑 / 集成测试未自动跑（点5 谨慎）。

### 已知遗留
- 用户 JWT 签发（网关 passport-jwt）与后端 PyJWT 验签的打通留到 Phase 2 网关。
- NDJSON 封装、alembic 迁移基线留到 p1.2。
- 种子密码占位 `__CHANGE_ME__`。

### 下一步
v1.0.0-p1.2：连接重试注入 / NDJSON 封装 / alembic 基线。

---

## v1.0.0-p0.1 — 项目脚手架 + Docker 联动（2026-10-18）

**类型**：脚手架 / 里程碑 0
**对应计划**：PLAN-1.0.0.md Phase 0
**Tag 提交**：见 `git show v1.0.0-p0.1`

### 交付内容
- 项目骨架 `office-multiagent/`（AIAgent 工作区下）。
- `docker-compose.yml` 串起 frontend / backend / mysql / redis / chroma（同 `office-net`，健康态依赖）。
- backend：FastAPI + `/api/v1/health` 联动探测三件套（chroma 缺失降级不致命）。
- frontend：nginx 反代 `/api` + 状态页。
- `db/init.sql`：核心表 + token 池 + 模型池（设计文档 §六/§十三/§十四）。
- `backend/requirements.txt`：已验证稳定版组合（pip dry-run 零冲突）。
- `docs/PLAN-1.0.0.md`：可执行分阶段计划。
- `tests/`：冒烟（免服务）+ 集成（默认 skip）。

### 验证状态
- ✅ `pytest backend/tests/test_smoke.py` 通过（免服务）。
- ✅ `docker compose config` 通过。
- ✅ 沙箱 SSH 到远程服务器可达（点6）。
- ⏸️ 全栈实跑 / 集成测试未自动跑（点5 谨慎，交显式执行）。

### 已知遗留
- 种子密码占位 `__CHANGE_ME__`；Chroma 镜像 `latest`（生产 pin）；网关 Phase 2 补。

### 下一步
Phase 1：后端核心骨架 → `v1.0.0-p1.1`。
