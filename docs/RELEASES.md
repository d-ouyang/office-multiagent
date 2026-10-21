# RELEASES · office-multiagent

> 每次打 tag 生成一条 release。纪律见 PLAN-1.0.0.md §3。
> 版本格式 `vX.Y.Z-pN.M`，老 tag 永不重打。

---

## v1.0.0-p6.11 — 钱包负余额保护（settle 下限保护）（2026-10-21）

**类型**：缺陷修复（账务正确性）
**Tag 提交**：见 `git show v1.0.0-p6.11`

### 交付内容
- `TokenPool.settle` 补差 `balance + refund` 用 `CASE` 钳在 0（MySQL/SQLite 原子成立），杜绝 `actual > reserved` 时余额穿负（p6.9 实测 -2493）。
- `reserve` 侧 `balance >= a` 原子保护不变；ledger 仍如实记录 `settle=actual`。

### 验证状态
- ✅ pytest 149 passed / 3 skipped（+3 回归用例：负余额穿底/恰好归零/ledger 留痕）。
- ✅ 复现 p6.9 场景：余额 1000、预扣 1000、实际 3493 → 余额 0（非 -2493）。

### 已知遗留 / 下一步
更彻底修复是任务级 token 硬上限（actual<=reserved 命中即硬中断），属成本治理，待点单；下一块建议 p6.12 附件引用闭环。

---

## v1.0.0-p6.7 — 过程透明 + 失败可观测 + trace 落库 + 打字机优化（2026-10-21）

**类型**：缺陷修复/体验（用户本地验证反馈 4 问题）
**Tag 提交**：见 `git show v1.0.0-p6.7`

### 交付内容
- **问题 4 修复（三层根因）**：observation 进 LLM 上下文改为结构化摘要（不再塞 8000 字 dict repr）；协议显式禁 action=none；连续 2 次无效工具名 → 强制如实收尾；general 提示词防重复读（8 次 → 1 次）。
- **问题 2（过程落库）**：迁移 0003 message.trace（JSON 全量事件）；GET messages 返回 trace；前端历史按 trace 重建折叠思考/步骤/md 渲染，刷新不丢失。
- **问题 1（打字机）**：JSON 包装的终答改 5 字/块切片推（12ms/块），与自然语言真流式路径视觉一致。
- 落库异常改 ERROR 级（trace 首版 json.loads NameError 静默失败的自愈）。

### 验证状态
- ✅ pytest 142 passed / 3 skipped（+4）；前端全绿。
- ✅ 问题 4 原样输入复测：read_document 1 次 → 216 delta → 成功总结；trace 226 事件回读完整。

### 下一步
p6.8 附件引用（输入框上方附件 chip + 拖拽 + attachments 随消息，方案见迭代文档 §4）。

---

## v1.0.0-p6.6 — 文档上传入口（2026-10-20，五任务收口）

**类型**：功能（文档链路闭环）
**Tag 提交**：见 `git show v1.0.0-p6.6`

### 交付内容
- `POST /api/v1/documents`（multipart）：落 data/upload/<username>/，basename 拍平 + 格式白名单 + 10MB + 空文件拒；python-multipart 入依赖。
- 前端输入条 📎 上传按钮（FormData，成功/失败提示）；read_document 描述补"不存在不重试"。
- compose data 卷改 rw（上传写入；护栏不依赖卷权限）。

### 验证状态
- ✅ pytest 138 passed / 3 skipped（+6 上传用例）；前端全绿。
- ✅ 真链路：上传 → read_document 逐字总结。
- **五任务（1 流式 → 2 会话 → 4 token 真账 → 3 模型生效 → 5 上传）全部完成。**

### 下一步
改密端点+token_version、RAG employee_id 加列、管理端、Phase 7 部署。

---

## v1.0.0-p6.5 — 模型选择真正生效（2026-10-20）

**类型**：功能（模型选择）
**Tag 提交**：见 `git show v1.0.0-p6.5`

### 交付内容
- /tasks 收 `model`（优先级：请求 > 会话默认 > 服务端默认；未知模型 400 fail-closed）；`PATCH /sessions/{id}` 更新会话默认模型。
- run_task(model=...) 透传 single/multi 的 brain（model_id）；settle 落账记实际模型。
- 前端：ModelPicker 切换即 PATCH 会话默认 + 请求带 model（localStorage 持久）。

### 验证状态
- ✅ pytest 132 passed / 3 skipped（+3：PATCH 流程/未知模型 400/透传断言）；前端全绿。
- ✅ 真链路：PATCH qwen-plus → 任务按它执行 → ledger 落账 model=qwen-plus。

---

## v1.0.0-p6.4 — token 池真账 + /quota（2026-10-20）

**类型**：功能（计费闭环）
**Tag 提交**：见 `git show v1.0.0-p6.4`

### 交付内容
- /tasks 按登录身份 reserve/settle（estimate 默认门槛 2000 + settle 真实补差，§十四 两段式闭环）。
- TokenPool.recent + GET /api/v1/quota（余额+流水，登录保护）；钱包种子 100000；settle 落账带 model。
- 前端：侧栏余额展示 + done 刷新 + quota_paused 警告条。

### 验证状态
- ✅ pytest 129 passed / 3 skipped（+2）；前端全绿。
- ✅ 真链路：100000 → 真 LLM 任务（真扣 3011）→ 96989，ledger 两行配对吻合。

### 下一步
p6.5 模型选择真正生效。

---

## v1.0.0-p6.2c — 会话持久化 API + 身份解析（2026-10-20）

**类型**：功能（会话层）
**Tag 提交**：见 `git show v1.0.0-p6.2c`

### 交付内容
- `core/identity.py`：Bearer token → PyJWT 二次验签（sub=employee_id）→ user 行；fail-closed。
- `core/session_repo.py` + 迁移 0002：message 表 + task 记录列；sessions REST（建/列/历史，归属校验防越权）。
- `/tasks`：session_id 支持（不传自动建）+ worker 落库（user/assistant 消息 + task 记录）+ 强制登录身份。
- 前端：侧栏接真会话（初始加载/新建/切换历史）；ChatMessage 历史终答直渲染。
- compose 注入 JWT_SECRET；Dockerfile 补 COPY alembic.ini/migrations。

### 验证状态
- ✅ pytest 127 passed / 3 skipped（+6）；前端 tsc/vitest/build 全绿。
- ✅ 真链路四步：建会话 → 真 LLM 任务 → 历史回读 → 列表标题。
- ⚠️ 踩坑记录：alembic 现有库需 stamp 0001 再 upgrade；Text(length) 与 DATETIME(6) 默认值的 ORM 渲染坑。

### 下一步
p6.4 token 池真账。

---

## v1.0.0-p6.3 — 真流式管道（打字机）+ 编排异常体面收尾（2026-10-20）

**类型**：体验/架构（流式管道）
**Tag 提交**：见 `git show v1.0.0-p6.3`

### 交付内容
- `chat_stream()`：httpx stream=True 逐 chunk 回调 + reasoning_content 思考流 + usage 末块。
- LlmBrain 流式混合策略：JSON 等完整 / 自然语言边收边推 content_delta（真打字机）；ReAct 协议升级"二选一"。
- `/tasks` 改 worker 线程 + queue + 同步 gen 实时转发（事件循环零阻塞）；run_task 加 sink + 异常 error/done 收尾。
- 修 multi 子任务事件不进流旧疾（子 emitter→主 emitter，seq 单调）；MarkdownView 流式 80ms 节流。
- agents.yaml：rag_retrieval 检索上限 2 次（真跑发现过度重试）。

### 验证状态
- ✅ pytest 121 passed / 3 skipped（+8 流式用例）；前端 tsc/vitest/build 全绿。
- ✅ 真链路实测：终答 173 个 content_delta 连续 1-2ms 到达（0.87s 打完）。

---

## v1.0.0-p6.2b — 模型注册表扩充（硅基流动渠道）+ backend config 热更卷（2026-10-20）

**类型**：配置
**Tag 提交**：见 `git show v1.0.0-p6.2b`

### 交付内容
- models.yaml 新增 deepseek-v3-sf / deepseek-r1-sf（硅基流动渠道 DeepSeek，与官方 key 额度独立互为备份）；对话模型共 7 个。
- compose backend 挂 `./backend/config:ro`：yaml 配置改完 recreate 即生效，无需重建镜像。
- 硅基流动 key 注入根 .env / backend/.env（gitignored）；qwen-plus 真调验证通过。

### 验证状态
- ✅ /models 返回 7 个模型；硅基流动链路真调通过。

---

## v1.0.0-p6.2a — 前端聊天式 UI 改版（参考 RAG 布局）（2026-10-20）

**类型**：前端
**Tag 提交**：见 `git show v1.0.0-p6.2a`

### 交付内容
- 布局重构：AppSidebar（会话列表/新会话/用户信息/退出）+ 聊天主区（header/消息流/输入条含模型切换），RAG ChatView 同构布局。
- 聊天流：用户右气泡 / 助手消息 = 深度思考折叠 + 步骤折叠 + markdown 正文；多轮消息累积（done 固化）。
- markdown：marked + DOMPurify；`renderMarkdownSmart` 阈值判断——<20k 主线程、≥20k 走 md.worker。
- 登录页居中卡片；模型切换下拉（暂存 localStorage，后端链路留 p6.5）。

### 验证状态
- ✅ tsc + vitest 21 + vite build 全绿；容器重建（8080）。

---

## v1.0.0-p6.1 — 登录链路（网关签发 sub=employee_id）+ 前端工作台 + 事件循环阻塞真修（2026-10-20）

**类型**：安全/功能
**Tag 提交**：见 `git show v1.0.0-p6.1`

### 交付内容
- user 表加 `employee_id`(UNIQUE)/`role`、删 `kb_role` 借名列；dev 种子 EMP001/dev/Office@2026。
- 网关登录（认证单点）：POST /api/v1/auth/login（bcryptjs 校验 → 签 JWT sub=employee_id）+ /auth/me。
- 前端登录页 + token + 401 回登录 + WorkspacePage 真工作台（发真 /tasks）。
- ⚠️ 真修事件循环阻塞：/tasks 同步 run_task 占死循环 → run_in_threadpool（后为 p6.3 队列管道取代）。
- compose：backend 注入 DEEPSEEK key + RAG_BASE_URL=host.docker.internal；gateway 注入 GATEWAY_MYSQL_*。

### 验证状态
- ✅ pytest 113 / jest 33 / vitest 21；容器全链路实测（login→token→/tasks 真检索真引用）。
- ✅ 手动验证文档：docs/手动验证-p6.1-登录与真链路.md。

---

## v1.0.0-p5.2 — 文档读取工具 + Demo 页 Agent 身份徽章 + db_query 实库验证（2026-10-20）

**类型**：能力（工具池补全 + 前端可视化）
**Tag 提交**：见 `git show v1.0.0-p5.2`

### 交付内容
- `read_document` 工具：路径穿越护栏 + 格式白名单（.md/.txt/.pdf）+ 截断如实标注。
- Demo 页"当前回答 Agent"徽章：single_node 发业务 Agent status 事件，前端 derive 派生 + 中文映射。
- compose backend 挂只读文档卷；pytest basetemp 固化项目内。

### 验证状态
- ✅ pytest 113 passed / 3 skipped；前端 vitest 21 passed + tsc + vite build。
- ✅ 真 LLM 端到端：读文档任务 → Brain 调 read_document → 总结要点；徽章事件真流验证。
- ✅ db_query 实库（容器内真 MySQL）：user 表真实结构与种子行、DROP 被拒、错列名如实上抛。
- ✅ 容器内 read_document 读挂载卷 ✅。

### 下一步
前端登录态 /tasks 打通；文档上传入口；multi 可视化细化。

---

## v1.0.0-p5.1b — 业务 Agent 提示词化 + 真 LLM 端到端（2026-10-19，Phase 5）

**类型**：能力（办公能力池 · Agent 层）
**Tag 提交**：见 `git show v1.0.0-p5.1b`

### 交付内容
- `config/agents.yaml`：7 个业务 Agent（6 业务 + general）的角色提示词 + 工具白名单（配置驱动）。
- AgentSpec 加载/回落/白名单裁剪；single 与 multi 子任务均按 spec 装配 Brain。
- 角色指令与 ReAct JSON 协议分离（协议由 brain 统一保证，防 7 份提示词漂移）。
- `tests/conftest.py`：单测强制无 LLM key（回落 StubBrain），真 LLM 验证只走显式 smoke。
- DEEPSEEK_API_KEY 搬入 backend/.env（用户授权，git-ignored）。

### 验证状态
- ✅ pytest 103 passed / 3 skipped（4.55s，纯 mock）。
- ✅ 真 LLM 端到端：rag 任务真检索并注明依据文件；无工具 Agent 如实告知能力未接入。

### 下一步
db_query 实库验证（compose MySQL）；文档解析工具（p5.2）。

---

## v1.0.0-p5.1a — 真实工具层 + LLM 客户端 + Brain 接入（2026-10-19，Phase 5 首步）

**类型**：能力（办公能力池首批）
**Tag 提交**：见 `git show v1.0.0-p5.1a`

### 交付内容
- `core/llm.py`：OpenAI 兼容客户端（models.yaml 注册表驱动，密钥 Settings→env 两级，usage 提取，fail-closed）。
- 真实工具：`db_query`（只读硬护栏：单条 SELECT、禁分号、词边界拦写、强制 LIMIT）、`rag_retrieve`（走 RAG 内部接口带网关证明）。
- `orchestration/brain.py`：LlmBrain（ReAct JSON 决策，坏输出/不可用→如实停止不编造，usage 累计）+ `make_brain` 配置驱动回落 StubBrain。
- graph：single 走 make_brain；`tokens_used` 进 state，settle 用真实用量（§十四 闭环）。

### 验证状态
- ✅ pytest 95 passed / 3 skipped（+30：llm/tools_db/tools_rag/brain，全 mock 不花钱）。
- ✅ 真实 RAG 工具 smoke：rag_retrieve → 本机 RAG → route=rag_qa 真通。
- ⏸️ 真 LLM 调用待本机配 DEEPSEEK_API_KEY；db_query 实库待 compose；Agent 提示词化 → p5.1b。

### 下一步
p5.1b：6 个业务 Agent 提示词化 + 真 LLM 端到端联调。

---

## v1.0.0-p5.0b — rag 上游按上游身份注入 + 剥客户端身份头（2026-10-19）

**类型**：安全（共享网关 Phase B 收口；配 rag 仓 p4.11）
**Tag 提交**：见 `git show v1.0.0-p5.0b`

### 交付内容
- 路由表增 `strip_identity` / `inject_identity` / `internal_secret`；rag 上游启用。
- `proxyReq`：剥 9 个客户端身份头（与 RAG IDENTITY_HEADERS 对齐）+ 注入 `X-Username` + `X-Internal-Auth`；**刻意不注 X-User-Id**（跨系统 id 撞行风险，走 username 回落，fail-closed）。
- env/compose 加 `RAG_INTERNAL_SECRET`（须与 RAG `OFFICE_GATEWAY_SHARED_SECRET` 同值）。

### 验证状态
- ✅ jest 28 passed / 4 suites（e2e：注入/剥离/伪造头/correlation-id 全断言）；tsc + build 通过。
- ⏸️ 与 RAG gateway 模式真实联调待生产/联调环境；身份对齐（username）为数据前提。

### 下一步
回 office 主线 Phase 5 办公能力池。

---

## v1.0.0-p5.0a — 共享网关：配置驱动路由表 + 多上游 + 横切加固（2026-10-19）

**类型**：架构（共享网关 Phase A/B/C；认证放 B）
**对应**：《共享网关迁移设计》
**Tag 提交**：见 `git show v1.0.0-p5.0a`

### 交付内容
- `gateway/config/routes.yaml` + `proxy/route-table.ts`：配置驱动路由表（多上游 + 最长前缀 + public + 前缀剥离 + `${ENV}` 展开）。
- `proxy.controller.ts` 重构为单通配按表解析、每上游动态代理、剥前缀、透传 correlation-id；守卫公开判定改读同一张表。
- Phase C：`AllExceptionsFilter` 统一错误体；`FixedWindowCounter`+`RateLimitMiddleware` 每 IP 限流（配置驱动，0=关闭）。
- 修复：gateway 运行阶段补 `COPY config/`；`js-yaml` 入依赖；compose/env 加 `RAG_BACKEND_URL`、`GATEWAY_RATE_LIMIT_*`。

### 验证状态
- ✅ `tsc --noEmit` + `nest build` 通过。
- ✅ `jest` 26 passed / 4 suites（route-table 10 + rate-limiter 4 + e2e 多上游/剥前缀/correlation-id/NO_ROUTE）。
- ⏸️ RAG 上游真实连通 + RAG 侧去双认证属部署态/跨仓，见设计文档 Phase B。

### 已知遗留
- 限流每实例内存；全局限流/多副本 LB/独立 IdP 留后续；RAG 后端改造跨仓未做。

### 下一步
本机验证 /rag/* 打通宿主 RAG；推进 rag 仓信任改造；回归 office Phase 5 办公能力池。

---

## v1.0.0-p4.2b — 与 RAG 同机共存：端口去冲突（2026-10-19）

**类型**：整合修复（compose）
**Tag 提交**：见 `git show v1.0.0-p4.2b`

### 交付内容
- `docker-compose.yml`：去掉 office `mysql/redis/chroma/backend` 宿主端口映射（内网 only，§12.3/§13.3）；`gateway` 宿主端口改 `3001`（避 RAG 的 3000）。
- 解决 RAG 宿主进程占 8000/3000、rag 中间件占 3306/6379/8001 导致的端口遮蔽 + office 中间件被踢出 office-net（backend 曾 degraded）。

### 验证状态
- ✅ 本机实跑：office-net 含全部 6 容器；backend /health 全绿；前端 :8080→nginx→office-gateway→office-backend NDJSON 通；宿主 :3001 → office-gateway；RAG 不受影响。
- ✅ 应用单测仍 65 passed（未改应用代码）。

### 最终端口
frontend 8080 / gateway 3001 / backend·mysql·redis·chroma 内网 only。

### 下一步
Phase 5 办公能力池。

---

## v1.0.0-p4.2a — 三层联调 + Compose 就绪修复（2026-10-18）

**类型**：整合验证 / 修复（Phase 4 收尾）
**Tag 提交**：见 `git show v1.0.0-p4.2a`

### 交付内容
- **修真 bug**：`backend/Dockerfile` 补 `COPY config/`（原漏拷 `models.yaml`/`planner.yaml`，容器内 /models·/plan·/tasks 会 500）。
- `docker-compose.yml` infra pin `mysql:8.0` / `chromadb/chroma:0.5.23`；gateway/frontend 基线用已缓存 tag。
- **三层真联调（宿主进程）**：网关→真后端公开 NDJSON 透传 ✅、受保护 401 ✅、有效 JWT→真编排 NDJSON ✅（闭合 p2.1a 假后端未覆盖的链路）。

### 验证状态
- ✅ 应用单测 65 passed / 3 skipped（未改应用代码）。
- ✅ 宿主进程三层真 HTTP 联调通过。
- ⏸️ 五容器 `docker compose up --build` 沙箱内未跑通（Docker registry 出网受限，`python:3.13-slim` 拉不动）→ 交本机执行，配置已就绪。

### 已知遗留
- 五容器 compose 实跑、真实 mysql/chroma 联调、真实 LLM 均待（本机 / Phase 5）。

### 下一步
本机 `docker compose up --build` 跑通五容器；Phase 5 办公能力池。

---

## v1.0.0-p4.2 — Token 池两段式扣减 + 中断 + 断点续跑（2026-10-18，Phase 4 收口）

**类型**：核心机制（Phase 4 后半）
**对应计划**：PLAN-1.0.0.md Phase 4 / v1.0.0-p4.2
**Tag 提交**：见 `git show v1.0.0-p4.2`

### 交付内容
- `core/token_pool.py`：`TokenPool` reserve（原子 `UPDATE...WHERE balance>=x` 防超额）/ settle（补差）/ balance，落 `token_ledger`；参数化 SQL 跨 MySQL/SQLite。
- `graph.py`：`quota` 门节点——reserve 失败 `interrupt()` 暂停（checkpointer），`Command(resume=...)` 充值后续跑；完成 settle。
- `POST /api/v1/tasks` 增 `user_id`/`estimate`，走 token 池，余额不足推 `quota_paused`。

### 验证状态
- ✅ `pytest backend/tests`：65 passed / 3 skipped（token_pool 5 + graph_token 3，含中断后续跑、原子不超额）。
- ⏸️ 三层真实联调（compose）下一步做。

### 已知遗留
- 真实 token 计数随 LLM brain（Phase 5）；跨请求续跑需持久化 checkpointer（SqliteSaver/MySQL）。

### 下一步
三层真实联调（compose up）整合验证；之后 Phase 5 办公能力池。

---

## v1.0.0-p4.1 — Orchestrator + 单 Agent ReAct + 工具兜底（2026-10-18）

**类型**：核心机制（Phase 4 前半）
**对应计划**：PLAN-1.0.0.md Phase 4 / v1.0.0-p4.1
**Tag 提交**：见 `git show v1.0.0-p4.1`

### 交付内容
- `orchestration/tools.py`：工具注册 + 退避重试（≤2）+ 能力缺失不胡编（§四.5）。
- `orchestration/react.py`：ReAct 循环 + max_iterations 防跑飞（超限强制阶段结论）+ Brain 协议 + StubBrain 确定性基线。
- `orchestration/orchestrator.py`：DAG 拓扑分层（topo_levels）+ 按层调度汇总（run_dag）。
- `graph.py`：single→run_react / multi→run_dag，共享 emitter 保 seq 单调。

### 验证状态
- ✅ `pytest backend/tests`：57 passed / 3 skipped（tools/react/orchestrator + /tasks 端点回归）。
- ✅ **后端编排闭环真跑**（uvicorn + curl）：/plan 简单→single、复杂→multi+DAG；/tasks 复杂任务按拓扑序 cleaning→analysis→report 推 NDJSON（seq 单调）；简单任务走单 Agent ReAct。
- ✅ 闭环抓到真 bug（/tasks 漏 import encode_line）并修 + 补回归。
- ⏸️ 未接真实 LLM / 未跑 mysql/chroma / 三层真实联调（交 compose 整合验证）。

### 已知遗留
- StubBrain 非真实推理；run_dag 层内串行未并行；token 池 + 断点续跑（p4.2）。

### 下一步
`v1.0.0-p4.2`：token 池两段式扣减 + 中断 + 断点续跑；三层联调（compose）整跑 case。

---

## v1.0.0-p3.2 — DAG 子任务拆分（2026-10-18，Phase 3 收口）

**类型**：核心机制（Phase 3 后半）
**对应计划**：PLAN-1.0.0.md Phase 3 / v1.0.0-p3.2
**Tag 提交**：见 `git show v1.0.0-p3.2`

### 交付内容
- `config/planner.yaml` 新增 `dag.dependencies`（意图依赖表，配置驱动）。
- `core/decomposer.py`：`decompose(plan) -> DAG`（子任务 + 依赖边），Kahn 拓扑排序 + 环 fail-fast，缺席依赖自动忽略。
- `orchestration/graph.py`：multi 节点按 DAG 子任务逐个推 status 事件 + task_summary。
- `POST /api/v1/plan` 复杂任务附带 `dag`（subtasks + topo_order）。

### 验证状态
- ✅ `pytest backend/tests`：45 passed / 3 skipped（新增 test_decomposer 6 例，含环检测）。
- ⏸️ 未接真实 LLM / 未跑全栈闭环（点5；闭环走通再整跑 case）。

### 已知遗留
- 规则 DAG 依赖模型是常见流程先验，LLM 分解插槽后续接；子任务未落库（留 Phase 4）。

### 下一步
**Phase 4（p4.1）**：Orchestrator 调度 + 单 Agent ReAct + 兜底 + 断点续跑；届时补全栈闭环再整跑 case。

---

## v1.0.0-p3.1 — Planner + Router：意图识别 / 复杂度打分 / 路由（2026-10-18）

**类型**：核心机制（Phase 3 前半）
**对应计划**：PLAN-1.0.0.md Phase 3 / v1.0.0-p3.1
**Tag 提交**：见 `git show v1.0.0-p3.1`

### 交付内容
- `config/planner.yaml` + `core/planner.py`：意图识别（6 类 → Agent 类型）+ 复杂度打分（步骤/多意图/多输出/长度/依赖，`signals` 可解释），**配置驱动确定性规则**（§十二：高频低延迟判断交给代码，LLM 留插槽）。
- `core/router.py`：按 `complex_threshold` 分流 single/multi。
- `orchestration/graph.py`：LangGraph `planner → 条件路由 → single/multi 桩节点 → END`，共享 `RunEventEmitter` 保 seq 单调，推 NDJSON 事件。
- `POST /api/v1/plan`（路由决策）+ `POST /api/v1/tasks`（跑编排、NDJSON 流式），均受网关 JWT 保护。

### 验证状态
- ✅ `pytest backend/tests`：39 passed / 3 skipped（新增 test_planner 6 + test_graph 3）。
- ✅ 覆盖简单→single / 复杂→multi、意图分类、signals 可解释、路由驱动 LangGraph、事件 seq 单调。
- ⏸️ 未接真实 LLM / 未跑全栈（点5）。

### 已知遗留
- 规则版对歧义/口语可能误判（signals 可解释 + LLM 插槽缓解）；`/tasks` 桩 Agent + 收集后流式；完整实体抽取随 p3.2。

### 下一步
`v1.0.0-p3.2`：DAG 拆分子任务。

---

## v1.0.0-p2.1b — 前端执行可视化 + NDJSON 流式 hook（2026-10-18，Phase 2 收口）

**类型**：流式协议 + 中间层（Phase 2 后半）
**对应计划**：PLAN-1.0.0.md Phase 2 / v1.0.0-p2.1b
**Tag 提交**：见 `git show v1.0.0-p2.1b`

### 交付内容
- 前端升级为 React 18 + Vite 5 + TS（多阶段 Dockerfile：node build → nginx 伺服 dist + 反代 `/api`→gateway）。
- `lib/ndjson.ts`（LineBuffer + parseEvent）、`lib/consume.ts`（consumeNdjson 流式消费）、`lib/derive.ts`（事件→toolCalls/正文/思考/产物/来源）。
- `hooks/useNdjsonStream.ts`（fetch + AbortController + 状态机）。
- `components/ToolCallsCollapse.tsx`（移植 weight-loss-agent 同名组件，去 tdesign 用 lucide + CSS 变量）+ `EventTimeline` + `DemoPage`（拉 `/api/v1/demo/stream` 渲染执行过程）。

### 验证状态
- ✅ `tsc -b` 通过；`vite build` 成功（gzip 51KB）。
- ✅ `vitest run`：17 passed（ndjson / consume / derive / ToolCallsCollapse）。
- ⏸️ 全栈 `docker compose up` 未自动跑（点5 谨慎）。

### 已知遗留
- §15.2 Worker/MD/虚拟滚动优化未接（先保可测 inline 消费）；登录态执行可视化等 Phase 3 任务端点。

### 下一步
**Phase 3（p3.1）**：Planner + Router。

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
