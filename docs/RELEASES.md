# RELEASES · office-multiagent

> 每次打 tag 生成一条 release。纪律见 PLAN-1.0.0.md §3。
> 版本格式 `vX.Y.Z-pN.M`，老 tag 永不重打。

---

## v2.0.0-p5.8 — 管理端任务监控增强：执行模式 / Agent 链 / 子任务归属 / 工具来源（2026-11-08，**本地分支，未打 tag / 未部署**）

**类型**：可观测性（用户需求：任务监控看不出单/多任务、触发了哪些 Agent、工具来自哪个池）

- **run_trace.summarize**：从 status 事件提炼 `mode`（done.status：single/multi）、`agents`（Agent 链，保序去重）、`subtasks`（multi 子任务 id→执行 Agent）；管理端 tasks 列表与 runs 详情自动携带。
- **前端任务详情抽屉**新增「执行编排」块：执行模式、Agent 链（如 planner→orchestrator→data_cleaning→data_analysis→report_generation→orchestrator）、multi 子任务归属、工具来源说明（single=主 Agent 白名单 / multi=各子任务各自白名单，均 agents.yaml；能力预检改道时为 general 全量池）。
- **测试**：+2（multi 全链路提炼、single 连续同名去重），基线 473 → **476 passed**；vitest 107 passed。本地 84 条历史任务全部解析出 mode/agents。
- 已知遗留（不阻塞）：FeedbackTab 存在三处 tsc 类型漂移（stash 验证为历史遗留，vite build 不受影响）。

---

## v2.0.0-p5.7 — 工具完善：query_orders columns 支持中文名，消除双调用浪费（2026-11-07，**本地分支，未打 tag / 未部署**）

**类型**：工具能力补齐（与 export_orders 列名语义对齐）

> 事故：A2 验证中「查一下最近 10 笔订单」两次调用 query_orders（3450+3304 tok）。trace 实证：第一次模型按 export_orders 的习惯传中文列名 `columns: ["订单号","下单时间",…]` → 工具报错"没有这些字段…请用订单表列名" → 模型自我纠正重试。**根因是工具间不一致**：export_orders 一直支持中文别名（_FIELD_SPECS），query_orders 只认数据库列名。

- **共享映射下沉**：`_COLUMN_LABELS`（35 列名↔中文名）从 tools_export 下沉到 orders_seed（两工具本就共同依赖它），export 以 import 别名保持零改动。
- **query_orders 认中文名**：columns 先按真实列名解析、再按中文名反向映射；混合传法支持。报错信息升级：未知列时**列出全部合法列名（含中文名对照）**，模型一次自我纠正即成。
- **Schema 描述同步**（agents.py）：query_orders 的 description 与 columns 参数说明注明"中文名或数据库列名均可"，模型第一眼可见。
- **测试**：+3（中文名全流程、中英混合、未知列报错含合法清单），基线 473 → **476 passed / 3 skipped**，全量零回归。
- **端到端实证**（rebuild 后实跑）：「查一下最近 10 笔订单，只要订单号、下单时间、门店、销售金额、订单状态这几列」→ 模型传中文名 columns → **第一次调用即 success**，7999 tok（原场景必烧 2 次调用）。
- **原 p5.7（放宽 intent_decision 触发条件）顺延**：p5.6 预检已覆盖同类风险，观察后再定。

---

## v2.0.0-p5.6 — 路由健壮化第二步：廉价预检（能力错配改道 general 兜底）（2026-11-07，**本地分支，未打 tag / 未部署**）

**类型**：路由加固（确定性，0 LLM）

- **机制**：planner.yaml 新增 `capability_guards`（强实体词 → 必需工具，当前 13 条：订单/退款/销售额/销量/发货→query_orders，制度/手册/知识库→rag_retrieve，图表/柱状图/折线图/饼图→render_chart，流程图→render_flow）；`router.decide` 在 **single** 路由上叠加预检——主意图 Agent 工具池不含问句实体所需工具 → 改道 `general`（全 14 工具兜底）。
- **边界**：multi 不预检（DAG 按意图分派各自专家 Agent，天然无错配）；primary 已是 general 跳过；agents.yaml 缺失时跳过预检（不因配置缺失放大影响）；预检只改 primary_agent 与 reason 追加说明，不动 mode/score。
- **设计原则落地**：路由只决定「从哪开始」，不决定「能做什么」——将来再配错关键词（如 orders 误配到无订单工具的 Agent），预检兜底接住，不再重演「查一下订单」401 事故。answer to「要不要放宽 intent_decision.is_ambiguous」：不改，预检以 0 LLM 成本覆盖同类风险，放宽触发条件留作 p5.7 可选。
- **测试**：+4（误配注入 monkeypatch 回归锚点、真实配置零误伤、图表实体撞清洗主意图改道、multi 豁免），基线 469 → **473 passed / 3 skipped**，全量零回归。
- **端到端实证**（rebuild + recreate 后 /plan 实测）：「查一下最近 10 笔订单」→ data_analysis；「清洗这张表然后画个柱状图」→ **general（预检改道）**；「查一下报销制度」→ rag_retrieval；「先查制度再分析」→ multi。
- **运维提醒**：backend/config 是挂载卷（yaml 热生效），但 backend/app 代码烧在镜像里——改代码必须 `build` + `up -d`，只 recreate 不生效。

---

## v2.0.0-p5.5 — 路由健壮化第一步：orders 意图 + 弱词降级（2026-11-07，**本地分支，未打 tag / 未部署**）

**类型**：缺陷修复 + 路由加固

> 分支 `feature/2.0.0-p5-reliability` 续推。事故源头：本地 p5 验证时「查一下最近 10 笔订单」被 planner.yaml rag 意图的弱关键词「查一下」劫持，路由进知识库 Agent（工具池无 `query_orders`）→ rag_retrieve 401。排查中发现 **compose backend 服务漏传 RAG_BASE_URL/RAG_INTERNAL_SECRET，生产 rag_retrieve 同样从未通过**（灰度 16 题未考 RAG 检索故未暴露），compose 修复已随本包提交（4e21b72）。

- **新增 `orders` 意图**：关键词 [订单, 退款, 销售额, 销量, 发货] → `data_analysis`（带 query_orders 等 12 工具）。orders 字母序在 rag 前，与 rag 同分时稳定胜出主意图。
- **「查一下」从 rag 关键词降级**：弱信号词不再单独定路由；制度/手册/知识库类问句靠强词（制度/手册/检索/知识库…）命中，实测「查一下报销制度」等问句路由不变。
- **single_agent_covers 同步**：analysis / report covers 补 orders（数据分析与报表 Agent 均带订单工具，副意图不触发误拆 multi）；orders covers [orders, analysis, cleaning, report, visualization]（rag 不覆盖——「按制度分析订单」保留真实跨能力交接）。
- **决策模型标签集同步**（intent_decision.py）：ALLOWED_INTENTS 与提示词补 `orders` 定义与示例「查一下最近10笔订单→orders single」；p6.32 的零命中触发决策模型路径对 orders 同样生效。
- **测试**：基线 464 → **469 passed / 3 skipped**（净增 5：事故回归锚点 1 + orders 关键词覆盖 1 + rag 强词回归 1 + covers 防误拆 1 + 决策模型透传 1）；全量零回归。
- **端到端实证**：本地全栈 recreate 后，事故原句「查一下最近 10 笔订单」→ data_analysis → `query_orders` 一次成功 → 流式终答（此前：rag_retrieval → 401）。
- **待办移交**：p5.6 廉价预检（实体→能力校验 + 冲突改道 general）、p5.7 LLM 路由兜底开关（decision 层已有，改触发条件）。

---

## v2.0.0-p5.1~p5.4 — 执行器可靠性加固（2026-10-31，**本地分支，未打 tag / 未部署**）

**类型**：稳定性（纯增量，缺省配置下线上行为零变化）

> 分支 `feature/2.0.0-p5-reliability`。按用户要求**不打 tag**（打 `v*` tag 会触发 CI 自动部署生产），因此本条目先记为本地工作成果，上线时再补正式版本号。

- **p5.1 LLM 重试补 429/500 + 参数配置化**：`_is_transient` 原先只做字符串匹配，**限流 429 与 500 完全不重试**——multi 层内并行打同一模型时，一次 429 就把已跑 N 步的子任务降级成「模型暂不可用」。改为状态码结构化判定（{429,500,502,503,504}）+ 网络错误字符串兜底；429 用独立更长的退避基数；`llm_max_retries` / `llm_retry_backoff` / `llm_retry_backoff_429` 配置化，缺省值与旧行为一致。
- **p5.2 DAG 层内子任务失败隔离**：此前 `as_completed` 里 `fut.result()` 让单个子任务异常拖垮整层、丢弃同层已完成成果。新增 `_run_subtask_guarded`，失败转为 `hit_cap=True` 的如实结果并继续执行，下游复用现有「未完成」标注感知；**`RunCancelled` 仍上抛**，用户暂停不被吞。
- **p5.3 工具级重试退避生效**：`ToolRegistry.call` 缺省 `backoff=0.0`（立即重试）改为读 `tool_retry_backoff`（0.3s）；只改间隔不改次数，非幂等工具副作用风险不变，显式 `backoff=0` 语义保留。
- **p5.4 checkpointer 可选 sqlite 持久化 + 真续跑**：新增 `checkpointer_backend`（缺省 `memory`，每次新建、现状不变）与 `orchestration/checkpoints.py`；`resume_task` 恢复为真续跑，并**先校验存档存在**——探针实测 langgraph 1.2.16 对无存档 thread 发 `Command(resume=True)` 会**静默从头重跑**（已完成节点重复执行）而非报错，该校验避免持久化失效时重复计费且无告警。新依赖 `langgraph-checkpoint-sqlite==3.1.2`，langgraph 版本未漂移。
- **两处盘点结论修正留痕**：①「LLM 零重试」不成立（p6.7b 起就有，brain 的 except 是耗尽后的降级）；②「venv_test 未装 langgraph」是 namespace package 导致的探测误判。
- 测试：**464 passed / 3 skipped**（基线 438，净增 26 = 单测 22 + 链路冒烟 4，零回归）。
- **链路级冒烟**：新增 `tests/test_p5_reliability_smoke.py`（4 条）——用 MockTransport 注入 429/500/工具故障，但真实经过 `llm.chat` 重试与 brain→run_react 完整链路，验证"重试后任务能跑完、流式不重复输出、降级如实"。两条 LLM 路径补重试日志（原先重试过程零日志，生产无法排查）。
- 手动验证用例与分工见 `docs/手动验证-p5-可靠性加固.md`。
- 详见 `docs/iterations/v2.0.0-p5.1-p5.4-reliability.md`。

---

## v2.0.0-p2.10 — 反馈回执契约收敛（rating）+ 部署磁盘防护（2026-10-29）

**类型**：缺陷修复（根因修复）+ 运维

- **真根因**：`feedback_repo.current_state()` 的评分字段用了 DB 列名 `feedback`，而消息列表契约与前端类型是 `rating`——POST 回执解析出 `rating=undefined`，点赞图标被打回空心。**GET 列表用 rating、POST 回执用 feedback，两接口字段名不一致**。统一为 `rating`（前端类型本就如此，前端零改动）。
- 前端契约守护：回执缺 rating 视为失败（回滚 + 就地报错），契约再坏也不会静默空心。
- 验证方式升级：Playwright 真实浏览器线上实测（点赞保持/取消保持/6 连点节流/恢复），不再只依赖单元测试。
- 磁盘防护：部署 workflow 末尾加 `builder prune --keep-storage 4g` + dangling image 清理（多轮 build 曾积压 ~30G 可回收层致瞬时打满）。

---

## v2.0.0-p2.8 — 反馈图标即时激活修复 + 节流（2026-10-29）

**类型**：缺陷修复

- 修复：点赞/点踩提交成功后图标被父级重渲染打回空心（useEffect 依赖 msg.feedback 冲掉本地乐观态）——改为父级在提交/取消成功后写回 messages + 子组件仅按消息 id 复位。
- 节流：反馈请求在途时忽略点击（ref 同步置位，同批次连点也拦得住），防暴力点击重复打接口；点赞/取消失败改为就地红字提示（此前错误只在点踩弹窗可见）。
- vitest 106 passed（+4 回归锚：父级重渲染不回退、节流、失败回滚、错误提示）。

---

## v2.0.0-p2.5 — 管理端尺寸对齐 rag admin-console（2026-10-27）

**类型**：前端样式

- office `/admin` 整套尺寸基准对齐 rag 管理端：正文 14px、控件高 34、表格 14px/10×12、表单间距 16、抽屉 1080→720px、侧栏 268→224、任务监控列宽按 14px 字号重算。纯样式无逻辑，vitest 103 passed。

详见 `docs/iterations/v2.0.0-p2.5-admin-compact.md`。

---

## v2.0.0-p2.4 — backend 句柄加固（2026-10-27）

**类型**：稳定性

- 生产事故复盘：backend 进程 socket 句柄耗尽（1023/1024，Errno 24）致全接口 500（"chroma 异常"为 health ping 连带的症状）。
- 加固：compose 为 office-backend 设 `ulimits.nofile=65536`；health 接口新增 `open_fds` 字段供水位观测。泄漏精确根因列入观察项。

---

## v2.0.0-p2.3 — 管理端「意见反馈」页（2026-10-27）

**类型**：功能（2.0.0 P2 管理侧，P2 收口）

- 新增 `/admin` 第六个一级入口「意见反馈」：统计卡（总量/点赞/点踩/点踩率/Top5 原因，点击原因即筛选）+ 评分/原因/关键词筛选 + 只读明细分页（含回答摘要与会话 id）。
- 后端 `GET /api/v1/admin/feedback`：统计口径不含评分筛选（总量稳定可比）；tag 筛选跨库兼容。只读纪律，不提供删改。
- P2 闭环至此三步全落：p2.1 数据/接口 → p2.2 用户侧弹窗 → p2.3 管理端。

详见 `docs/iterations/v2.0.0-p2.3-admin-feedback.md`。全量 pytest 436 / vitest 103。

---

## v2.0.0-p2.2 — 前端点赞/点踩闭环 + 反馈弹窗（2026-10-27）

**类型**：功能（2.0.0 P2 用户侧）

- 回复行点赞/点踩接真接口：激活态实心图标，再点实心 = 取消；DB 为真相源，刷新/切会话状态保持。
- 点踩弹窗：抱歉话术标题 + 8 个原因 tag 多选 + 「其他原因」多行输入（0/200）；至少选一个原因才能提交；遮罩点击不关闭。
- 已知边界：流式刚结束的本地消息暂不能反馈（无 message id），刷新后可反馈。

详见 `docs/iterations/v2.0.0-p2.2-feedback-frontend.md`。全量 vitest 103 passed。

---

## v2.0.0-p2.1 — 消息反馈数据模型与接口（2026-10-27）

**类型**：功能（2.0.0 P2 第一步）

- 迁移 0013：`message` 加反馈当前态四列 + 新增 `message_feedback` append-only 流水表（init.sql 与列级护栏同步）。
- 提交/取消反馈接口：二次点踩覆盖当前态且旧信息保留流水；dislike 强制带原因（tag 多选或文字 ≤200）；越权 404 同形。
- 会话消息列表带出消息 `id` 与反馈当前态，供前端渲染激活态。全量 pytest 433 passed / 3 skipped。

详见 `docs/iterations/v2.0.0-p2.1-feedback-model-api.md`。

---

## v2.0.0-p1.3 ~ p1.6 — brain 双协议 + react 执行环 + 协议开关 + E2E 对照（2026-10-27）

**类型**：2.0.0 改造（M2 收口）

- **p1.3 brain 双协议**：`tool_calls` 路径——历史改 `assistant(tool_calls) → tool(tool_call_id)`（观察只走 tool 角色，无历史双写），system 移除强迫 JSON 的段落（Prompt 债务红线）；json 路径逐字节不变。
- **p1.4 react 执行环**：一轮多 tool_calls 串行展开为动作单元，每个 call 独立 start/end/observation（tool_id 用原生 call id）；`parse_error` 不真执行、回工具错误观察；未知工具走 CAPABILITY_MISSING 可收敛；护栏（去重/无效连击/步数/取消）按单元粒度生效。
- **p1.5 协议开关**：`react_protocol: json | tool_calls | auto`，**缺省 json（上线行为不变）**；不支持模型或 Schema 不齐一律回落 json 并告警，禁止硬开。
- **p1.6 对照收口**：同任务双协议 E2E 同形事件对照通过；P1 验收 7 条中 6 条落✅、1 条待线上灰度实测。全量 pytest 423 passed / 3 skipped。

详见 `docs/iterations/v2.0.0-p1.3-*.md` ~ `v2.0.0-p1.6-*.md`。

---

## v2.0.0-p1.2 — llm.py 原生 tool_calls 协议面（2026-10-27）

**类型**：2.0.0 改造（协议面）

- `chat` / `chat_stream` 支持 `tools` / `tool_choice` 入参（缺省 auto，不带 tools 时请求体与改造前完全一致）。
- 新增 `ToolCall` 归一化结构：非流式解析 `message.tool_calls`；流式按 index 增量累积，流结束后一次性回调 `on_tool_call`，正文/思考流与工具增量分通道。
- 错误口径：缺 id/name 抛 LlmError；arguments 解析失败落 `parse_error` 不抛崩（由上层回填工具错误）。
- 全量回归 pytest 411 passed / 3 skipped。

详见 `docs/iterations/v2.0.0-p1.2-llm-tool-calls.md`。

---

## v2.0.0-p1.1 — 工具参数 Schema 与 OpenAI tools 导出（2026-10-27）

**类型**：2.0.0 改造准备

- `ToolRegistry` 支持注册参数 JSON Schema，新增 `describe_openai()` 导出 OpenAI 兼容 `tools[]`；缺 Schema 的工具被排除并有护栏测试。
- 全部 13 个工具补齐 Schema（与函数 kwargs 一一核对），白名单裁剪时 Schema 随行。
- 现有文本 ReAct 路径（`describe()`）不变，json 协议零影响。

详见 `docs/iterations/v2.0.0-p1.1-registry-schema.md`。

---

## v2.0.0-p3.1 / p4.1 — 侧边栏标题渐隐 + 对话区 1200px 居中（2026-10-27）

**类型**：前端体验

- 会话标题溢出且未滚动时右缘 26px 渐隐，能"看见"被截断文字的边缘；跑马灯滚动期间蒙层自动移除。
- 对话区新增统一内容列：消息流、会话标题、输入条共用 `min(1200px, 100%)` 宽度，宽屏居中两侧留白，窄屏整屏铺满，无横向滚动。

详见 `docs/iterations/v2.0.0-p3.1-p4.1-title-fade-center-column.md`。

---

## v2.0.0-p1.0 — 原生 tool_calls 能力基线与 golden（2026-10-27）

**类型**：2.0.0 改造准备

- 新增 `supports_tools` 三态能力字段，当前 10 个对话模型经真实点测，非流式与流式 tool_calls 全部通过。
- 冻结六类 golden（单工具/多工具/缺参/未知工具/纯终答/流式终答）与前端依赖的 NDJSON 事件契约。
- 提供可重复点测脚本；本步不切运行协议、不影响现有 ReAct JSON 路径。

详见 `docs/iterations/v2.0.0-p1.0-tool-calls-baseline.md` 与 `docs/tool-calls-能力基线.md`。

---

## v1.0.0-p6.46 — 手动停止落库 + 数据库聚合直通画图 + 模型池下线 Qwen（2026-10-26）

**类型**：修复 + 功能

- **手动停止的任务现在落库**：此前只有 `done` 才写会话消息，手动停止刷新后这轮对话凭空消失。
  现在 `paused_user` 会落用户消息 + 流式里实际推过的正文（quota/error 暂停仍不落——续跑是整轮重跑，落了会重复）。
- **"对数据库数据统计并画图"一类问题直通**：根因是 planner 把它路由给可视化 Agent，而该 Agent
  没有 query_orders，只能对空文件名调 clean_table 然后草草收场。修法是打通一类问题而非补单点：
  ① `query_orders` 分组统计自动存可分析副本并返回 `clean_id`（render_chart/analyze_table 直接消费）；
  ② 可视化 Agent 补上 query_orders，提示词写明两条数据路径；general/data_analysis/report_generation 同步加提示。
  实测三条快捷示例全部打通：统计+柱状图（query_orders→render_chart→svg）、9/10 月对比 PDF 报告、导出全国明细 xlsx。
- **模型池下线 Qwen 对话模型**（qwen3.5-9b / qwen3.8-27b，思考太慢）：对话模型剩 10 个；
  决策小模型 decision-llm（Qwen2.5-7B）保留——它不进对话列表且是路由必需。

---

## v1.0.0-p6.45 — 时间时区修复 + 逐步 token 用量浮窗（2026-10-26）

**类型**：修复 + 功能

- **时间快 8 小时（根因）**：共享 MySQL（rag-mysql）全局 `time_zone=+08:00`，列默认值
  `CURRENT_TIMESTAMP` 写的是北京墙钟；而 `_iso_utc` 按"库里是 UTC"给所有时间打 Z 标，
  前端再按 Z→本地 +8h 转换 → 会话列表/消息时间显示成"未来 8 小时"。
  修复：backend 连接级 `SET time_zone='+00:00'`（`core/db.py`，仅 mysql URL 生效），
  存储口径回归真 UTC；服务器存量行做一次性 `CONVERT_TZ('+08:00'→'+00:00')` 迁移。
- **逐步 token 用量浮窗**：`brain.usage` 每次调用后累计 → ReAct 循环逐步采样差值
  （`react.py` 的 `steps_usage`），single=规划+各步+外部用量、multi=规划+各子任务+汇总官；
  随 DONE 事件与 trace 落库（历史消息同样可看）。前端悬浮"共消耗"弹出逐步明细浮窗。

详见代码注释（`core/db.py` / `react.py` / `derive.ts`）。

---

## v1.0.0-p6.44 — 数据扩容到全国 + 演示账号 + 新会话示例 + CI/CD 文档（2026-10-26）

**类型**：功能 + 数据

- 订单扩到 **1500 条**：新增 20 个全国大城市门店（北上广深蓉杭汉宁渝等），增量 74% 落在新城市；
  时间窗 2026-09~10；字段与既有数据完全对齐（经 `orders_seed` 导入器校验，0 撞号）。
  种子主文件 `guoquan_orders_2025_2026_en.csv` 同步追加，未来全新安装一次灌全。
- 新增可复用工具：`backend/data/gen_orders_extra.py`（造数）、`backend/data/import_extra_orders.py`
  （增量补灌，只插不存在的 order_no，幂等——以后加数据就靠它）。
- 新增 6 个演示账号（1 管理员 + 5 员工，含钱包额度），种子 SQL `seed_demo_users.sql`（幂等）。
- 新会话欢迎语从一句静态文案改为**三张可点击示例卡**（数据/报告/导出三类核心能力），
  点击直接发起对应任务。
- 新增 `docs/CI-CD部署流程.md`：自托管 runner 注册 → workflow → 日常发布 → 回滚的完整手册。

详见 `docs/CI-CD部署流程.md` 与仓库内种子脚本注释。

---

## v1.0.0-p6.43 — 上线首日 hotfix：DNS 冲突 / init.sql 列漂移 / 输入条宽度（2026-10-26）

**类型**：修复

- **重大**：共享网络 DNS 服务名冲突——office 的 `backend/gateway/frontend` 服务名与 RAG 栈重名，
  加入共享网络后在 DNS 里轮询，rag-gateway 的上游一半请求打到 office-backend（404），
  造成 qa.nianan.site 间歇「服务离线」、管理端「认证服务暂时不可用」。office prod 服务名全部
  加 `office-` 前缀，前端 nginx 上游用独立 `nginx.prod.conf`。修复后 health 10/10 全 200。
- office 发消息/上传 500：`db/init.sql` 缺 `message.trace` 列（列级漂移）。生产库已补列，
  init.sql 已修，并**新增列级护栏测试**（REQUIRED_COLUMNS 快照，缺列即红）。
- 底部输入条只占 400px：PromptBar bits 组件默认宽度，工作台内作用域覆盖为占满整行。

详见 `docs/iterations/v1.0.0-p6.43-hotfix-shared-infra.md`。

---

## v1.0.0-p6.42 — 生产部署上线 office.nianan.site（2026-10-26）

**类型**：部署

- 上线 `https://office.nianan.site`（含 `/admin`），形态为**共享 RAG 中间件**：只起 backend/gateway/frontend 三容器，mysql/redis/chroma 复用 RAG 栈同版本实例（设计 §12.3）；office 用独立 `office` 库 + 专用用户 + redis db 2。
- 新增 `docker-compose.prod.yml`（与开发 compose 分离；外部网络按容器名访问 RAG；宿主端口只绑 127.0.0.1，前端 8090）。
- backend/Dockerfile 修 Debian 源卡死（deb.debian.org 出海极慢 → mirrors.cloud.tencent.com，与 1024 的 apk 修复同款）。
- 建库走既定路径：init.sql 灌库 + `alembic stamp head`（顺带发现 0001 迁移多语句 bug，留待修复）。
- 冒烟全过：健康检查三件套 ok、首页/`/admin` 200、用户与管理端登录均出 token、到 RAG 检索服务网络连通。
- ⚠️ dev 种子账号（role=admin）密码哈希在仓库里，上线后应立即改密或停用。

详见 `docs/iterations/v1.0.0-p6.42-prod-deploy.md`。

---

## v1.0.0-p6.41 — 引入 Skill 能力层 P1（2026-10-26）

**类型**：架构（不改动运行时）

- 新增 `backend/app/skills/`：Tool（原子函数）/ Skill（能力包）/ Agent（运行时）三层拆开，
  补齐参考架构缺失的「Agent Skills」组件。
- 一个 skill 一个目录：`spec.yaml`（触发条件 + 工具白名单 + 记忆权限）+ `prompt.md`（指令）+ 可选 `run.py`。
  工具从 Agent 视角隐身，成为 skill 的实现细节。
- 示例 `doc_writing`：包住现有 `write_document`，只加护栏不重实现；`enabled` 缺省关闭，fail-closed。
- **只新增，不动运行时**：`router.py` / `agents.py` / `orchestrator.py` 未改。测试 10 例全过。

详见 `docs/iterations/v1.0.0-p6.41-skill-layer.md` 与 `docs/项目架构调整-引入Skill层-2026-10-24.md`。

---

## v1.0.0-p6.40 — 管理端 antd 深色主题与表格/用量/审计打磨（2026-10-26）

**类型**：功能 + 修复

- `/admin` 引入 antd 深色主题，**按需引入**（收口在 `admin/ui.ts`），聊天工作台不受影响。
- 表格改底部分页 + 即时筛选（防抖）；列宽按比例、只保留一层纵向滚动、长文本省略；任务 id 与用户工号点击复制。
- 用量概览换成按模型分色的竖向柱状图，只有柱子顶部圆角。
- 任务详情用 SVG 画 Q→A 实走路径；任务表补工具摘要。
- 模型池显示模型 id、编辑改抽屉，可在管理端**新建模型**（只写 `models.overrides.yaml`，不动手写的 `models.yaml`）。
- 部署：`docker-compose.yml` 中 `./backend/config` 挂载去掉 `:ro`，否则管理端写 overrides 会失败。

详见 `docs/iterations/v1.0.0-p6.40-admin-antd-polish.md`。

---

## v1.0.0-p6.39 — 输入条单击 + 模型上限校对 + 管理端改版（2026-10-25）

**类型**：功能 + 修复

- 修掉输入条要点两次：工具栏拉回焦点时会误触发 `onFocus` 的关闭逻辑，现在跳过这一次。
- 「单次最多输出」按官方页校对 DeepSeek 官方与硅基 DeepSeek-V3/R1；这是 `models.yaml` 的配置值，不是运行时向厂商拉元数据。
- 管理端侧栏收敛为概览、任务监控、用户额度、模型池、审计日志；用量与系统状态并入概览。
- 任务监控合并运行溯源，详情用侧栏抽屉画 Q→A 节点流；用户额度支持精确搜索、余额筛选、充值弹窗与分页流水。
- 模型池按角色看可见模型，可改名称/描述/参数/渠道/启用。

详见 `docs/iterations/v1.0.0-p6.39-admin-overhaul.md`。

---

## v1.0.0-p6.38 — 管理端概览与运行溯源（2026-10-25）

**类型**：功能

- `/admin` 默认打开概览：暂停数、近 7 日失败、完成率、数字未对齐、服务健康点。待办可跳到过滤后的任务或溯源。
- 侧栏分成核心、次要、高级。模型池和系统状态在高级，并写明不是每天要做的事。当前操作者固定在侧栏上方。
- 配额暂停的任务可以「去充值」，用户列表会对准那个人。
- 运行溯源列出工具序列、产物、知识库身份是否和服务号不一致。任务表增加工具摘要，可按「曾检索知识库 / 数字未对齐 / 无产物」筛选。
- 知识库调用仍用服务号，返回里带上办公用户名，不一致就标红。角色说明写在 `docs/管理端-角色.md`。
- 登录失败只在密码下面用浅红色写一句，不再用粗红框。登录成功后请浏览器保存密码；密码错的那一次本来就不会记。

详见 `docs/iterations/v1.0.0-p6.38-admin-ia.md`。

---

## v1.0.0-p6.37 — 图片上传先 OCR 再交给对话模型（2026-10-25）

**类型**：功能

- 输入框可以选 png / jpg / webp。图片超过 4MB 会在上传时拒绝。
- 发送前用硅基流动上的 DeepSeek-OCR（`deepseek-ai/DeepSeek-OCR`）转成文字，写进本轮提示。对话模型仍然只收文本，不会说自己看见了画面。
- 普通文档仍让模型用 read_document 去读，不走这条识别。

详见 `docs/iterations/v1.0.0-p6.37-image-ocr.md`。

---

## v1.0.0-p6.36 — 余额不足横幅不再用旧余额、不再提供继续（2026-10-25）

**类型**：修复

- 横幅上的余额改读当前钱包。充值之后余额已经够付这次预扣，横幅不再出现。
- 余额不足时不再给「继续」。原来的继续是把整段提问重跑一遍，不是从停下的地方接着算。
- 系统设置里删掉「目前没有别的个人开关」那句说明。

详见 `docs/iterations/v1.0.0-p6.36-quota-banner.md`。

---

## v1.0.0-p6.35 — 上下文跟随模型，个人中心拆成独立面板（2026-10-25）

**类型**：交互

- 右上角上下文总量跟当前选中的模型走。切到 DeepSeek V4-Flash 立即显示 1024K，硅基 V3 显示 160K，不必等下一轮任务。
- 模型按 DeepSeek、Qwen、其他分组。悬停出介绍卡，文案来自 `models.yaml` 里已有的 description。
- 侧栏标题改为「锅圈 Agent / 企业级智能办公助手」，下面保留 office-multiagent。管理端入口移进个人中心。
- 用量、长期记忆、系统设置、修改密码各自用大弹窗。用量可按模型、时间和用量筛选，点一行跳到对应会话里的那次提问。
- 长期记忆分成四段可编辑背景（工作、个人、当前关注、近期记录），加上原来的短条目。系统设置里，单任务 token 上限和结果数字校验是全员开关，只有管理员能改；模型和力度仍是个人的，留在输入条。

详见 `docs/iterations/v1.0.0-p6.35-account-surfaces.md`。

---

## v1.0.0-p6.34 — PDF 中文字体修复（CFF 轮廓坑 + 失败可见化）（2026-10-24）

**类型**：修复（真机「再出一份，换成 pdf」用例阻塞项）

- **根因**：思源黑体/Noto CJK 是 **CFF（PostScript）轮廓**，reportlab `TTFont` 只认
  TrueType 轮廓，注册必败；异常被 `except: continue` 静默吞掉 → 「装了字体仍报没有字体」。
- **修复**：Dockerfile 加装 TrueType 轮廓的 `fonts-wqy-microhei`（noto-cjk 保留给 matplotlib 图表）；
  `_cjk_font()` 重写——TrueType 候选 + 字体目录兜底扫描 + 注册失败 WARNING 留痕，
  报错文案纠正（明确思源黑体不可用，`PDF_FONT` 仍最高优先）。
- **验证**：容器内端到端生成中文 PDF，pypdf 抽回文本完整、无康熙部首污染；
  新增 2 测试（失败路径报错含 TrueType 指引；注册失败留 WARNING）。

详细见 `docs/iterations/v1.0.0-p6.34-pdf-truetype-font.md`。

---

## v1.0.0-p6.33 — 决策小模型标签语义校准（2026-10-24）

- 真模型冒烟抓到「理由=查询上海销售，标签=general」的自相矛盾。
- 补齐 7 类标签定义、结构化业务数据判定原则和少样本示例。
- 真机复测「看看上海卖得怎么样」→ `analysis / single / data_analysis`。

详见 `docs/iterations/v1.0.0-p6.33-decision-label-grounding.md`。

---

## v1.0.0-p6.32 — 办公交付能力 + 混合意图识别 + 单任务 token 上限（2026-10-24）

**类型**：功能 + 稳定性 + 成本治理

- 订单查询/导出从城市和状态死名单改为按真实表字段筛选；任意城市、值列表、通用 filters、真实列名导出。
- `render_flow` + 前端 SVG 实走路径；数据图改为 ECharts（按需加载），后端仍产 svg/png。
- `write_document` 增 PDF/PPTX；新增代码计算的同比、环比、占比。
- RAG `persist=false` 外部完整工作流：不污染 RAG 会话/额度，带回重排分、依据和 usage，办公侧统一结算。
- 意图识别四步落地：指代改写、含糊句决策小模型、单 Agent 能力覆盖判定、规则/模型分歧日志。
- 全员单任务 token 上限默认 50,000（`TASK_TOKEN_HARD_LIMIT`），与钱包余额门分离；multi 共享预算。
- pytest **361 passed / 3 skipped**；vitest **81 passed**；tsc/build 通过；RAG 回归 55/0。

详细见 `docs/iterations/v1.0.0-p6.32-office-visual-intent-cap.md` 与 `docs/意图识别方案.md`。

---

## v1.0.0-p6.31 — 预览升级（去技术文案 + 下载 + 大文件分页预览）（2026-10-24）

**类型**：修复 + 功能（用户反馈三件套）

- **文案**：预览头部「服务器上的文件」→ 类型徽章；两处 title 去掉"服务器"——界面文案不出现技术名词（用户拍板原则）。
- **下载**：`/documents/content&download=true` 返回原始文件（此前 csv/xlsx 只有 20 行抽取文本，无真下载）；预览头部新增「下载」按钮。
- **大文件表格预览**：`GET /documents/table` 分页端点（csv/xlsx、xlsx 多工作表切换、limit≤200、路径校验同闸）+ 前端滚动增量加载（IntersectionObserver，首屏 50 行、滚动追加、表头吸顶、「共 N 行已显示 M 行」）。澄清：文件落盘即全量，20 行是 Agent 读表用的抽取上限泄漏到了预览。
- pytest **342 passed / 3 skipped**（+7）；vitest 80；真机 236 行 xlsx 滚动全量加载 + 下载验证。

---

## v1.0.0-p6.30 — 销售链路修正（planner 隔离/折叠 + export_orders + 图表嵌文档 + assets）（2026-10-23）

**类型**：修复 + 功能（复盘 run 074e6de7 三根因全修）

### 交付内容
- **P0 planner 输入隔离**：意图识别/复杂度/拆分只看本轮原文（`TaskState.raw_text`）——记忆注入块/历史摘要不再劫持意图（真跑事故：记忆"财务制度"触发 rag，2.5/single→4.5/multi+rag）。
- **折叠规则**：analysis/report/cleaning + visualization 同时命中时 viz 折进主意图（图表是内嵌产物，不拆独立子任务）；单独要图仍走 visualization。
- **export_orders**：订单明细导出 csv/xlsx（fields 指定列；手机号脱敏；缺字段整列省略如实说明；export_id 供画图）。
- **图表数据链**：render_chart 接受 export_id（xlsx 也能读回——真机抓到）；同时产 png；write_document 新增 image_file 嵌图进 docx/md；预览白名单放宽 e-/png/csv/xlsx。
- **assets 传递 + 汇总脑**：子任务间传文件资产（不只文本摘要）；multi 汇总不再原样拼接子任务终答（表格重复展示根因），汇总脑输出"核心结论+交付清单"，token 入账。

### 验证状态
- pytest **335 passed / 3 skipped**（新增 15 例）；tsc 干净。
- 真机（用户原任务逐字重放）：意图 `['analysis']`/1.0 → single；export xlsx 236 行（支付方式省略说明）→ render_chart(export_id) → docx 嵌图（zip media 验证）；终答无重复表格。

详细见 `docs/iterations/v1.0.0-p6.30-export-chain.md`、`docs/分析-2026-10-23-销售总结任务复盘.md`。

---

## v1.0.0-p6.29 — P1 两件套：轻量结果校验器 + 显式长期记忆（2026-10-23）

**类型**：功能（对照参考架构差距分析的拍板项：⑭ 结果校验器 + ④ 长期记忆）

### 交付内容
- **轻量结果校验器**：`orchestration/validator.py`——终答数字 vs 工具观察（含任务原文）对账，不新增 LLM 调用、不阻断、不重跑；只校验"硬数字"（≥1000 或带小数）压误报，万/亿/千分位/尾零归一化；对不上发 `result_validator` observation 事件 + WARNING（随 trace 落库）；single 按主任务、multi 按子任务各自对账；`RESULT_VALIDATION` 开关。
- **显式长期记忆**：迁移 `0011_user_memory`（只增不改、无 update_time/deleted）+ `user_memory_repo`（幂等去重、满了如实拒绝不淘汰、越权 404 同形）；`remember`/`recall` 工具（仅登录用户挂载，4 类 Agent 白名单可见）；每轮注入【用户长期记忆】块并计入 context_usage memory 分栏；用户 API `GET/POST/DELETE /api/v1/memory`；前端个人中心"长期记忆"视图（列表/添加/删除）。

### 验证状态
- pytest **320 passed / 3 skipped**（新增 validator 12 例 + user_memory 13 例）；vitest **80 passed**；tsc 干净。
- 真机：迁移至 `0011_user_memory (head)`；/memory 增查删全链路；真任务让 Agent 记偏好 → `source=agent` 落库 → 同会话追问正确答出（context_usage 出现 memory 分栏）；编造/推导数字场景 → 校验器事件如实标出 `179.51、4.3`（multi:report）；任务原文数字不误报（98765 未标）。Playwright 截图核对记忆视图。

### 文件
新增：`backend/app/orchestration/validator.py`、`backend/app/core/user_memory_repo.py`、`backend/app/orchestration/tools_memory.py`、`backend/migrations/versions/0011_user_memory.py`、`backend/tests/test_validator.py`、`backend/tests/test_user_memory.py`。
修改：`graph.py`（_validate_and_flag）、`agents.py`/`config/agents.yaml`（记忆工具挂载）、`routes.py`（/memory 端点 + 注入）、`orchestration/memory.py`（user_memory_block + context_items）、`config.py`（5 项配置）、`db/init.sql`、前端 `api.ts`/`AccountPanel.tsx`/`styles.css`。

---

## v1.0.0-p6.28 — 管理端体验补齐（审计日志 / 分页 / 统一下拉框 / 代续跑确认）（2026-10-23）

**类型**：功能（对照 RAG 管理端差距分析后的四项补齐）
**Tag 提交**：见 `git show v1.0.0-p6.28`

### 交付内容
- **审计日志（从 0 到 1）**：迁移 `0010_audit_log`（无 update_time/deleted_at）+ `core/audit_repo.py`（只写只读、动作白名单、敏感键值抛错拒绝）+ 8 类动作埋点（登录成败/登出/改密/充值/池分配/池增删成员/代续跑）+ `GET /admin/audit-logs`（筛选+分页）+ 前端审计板块（detail 按动作翻译成人话）。设计参考 RAG 的 audit_repo 三条结构性约束，代码未照搬。
- **管理端独立登录落到后端**：`POST /admin/login`（账密+角色+审计）、`POST /admin/password`（改密踢号发新 token）、`POST /admin/logout`（记账）；网关 routes.yaml 公开 admin/login。
- **列表分页**：users/tasks/audit-logs 全改 page/page_size + total；前端 `Pager`（总数/页码窗口/每页条数）。
- **统一下拉框**：轻量 `Select`（浮层+hint+键盘可达）替换三处原生 select。
- **代续跑确认与结果可见**：确认弹窗（讲清"重跑而非续跑、消耗记原用户、操作留痕"）+ 结果弹窗（终态/tokens/新任务 ID）。

### 验证状态
- ✅ pytest 295 / jest 40 / vitest 80；tsc 无错。
- ✅ 真机：错误密码 401 且落审计、充值 8000 审计明细完整、审计页 7 条含 IP。
- ✅ Playwright：确认弹窗文案、完整走通 确认→代续跑→结果弹窗（single / 3,716 tokens / 新任务 ID）、分页与下拉展开正常。

---

## v1.0.0-p6.27 — 管理端独立应用 + 代续跑 + 模型池配置（2026-10-23）

**类型**：功能
**Tag 提交**：见 `git show v1.0.0-p6.27`

### 交付内容
- **管理端独立应用**：`/admin` 独立登录页（独立 token `office_admin_token` + 角色校验，非管理员拒登）+ 侧边菜单（5 板块）+ 个人中心（信息/改密/退出）。修复"未登录访问 /admin 先掉进工作台登录页"的双重登录问题。
- **任务监控代续跑**：`POST /admin/tasks/{id}/resume`（不校验 owner，消耗记原 owner，操作人落 request_json.operator）；任务表操作列 + 结果提示。
- **模型池配置**（先补"配了也白配"的洞）：`/models` 按登录用户 `model_pool_id` 过滤（§十三 落地）；DB `pool_model` 显式配置优先、无记录回落 yaml；池身份=名字（default/staff/admin 种子）；管理端模型池板块（池列表/模型矩阵/新建/删除）+ 用户表池列分配。
- **数据**：init.sql 增加模型池种子（与 models.yaml 的 pool_ids 同名对齐）。

### 验证状态
- ✅ pytest 279 / jest 40 / vitest 73；tsc 无错。
- ✅ 真机：非管理员拒登；/models 按池过滤（dev 12 个 / chen 10 个，reasoner 隔离）；代续跑全链路（retry_of/operator/resumed/跑完 2546 tokens）；`/admin#usage` 刷新保持。
- ✅ Playwright 6 张截图核对（登录/拒登/用户额度/模型池/任务监控/个人中心）。

### 已知遗留
- 模型池只覆盖对话模型；代续跑在管理端只提示结果不展示过程流。

---

## v1.0.0-p6.26 — 管理端升级为独立页面（4 板块）（2026-10-23）

**类型**：功能（体验补齐）
**Tag 提交**：见 `git show v1.0.0-p6.26`

### 交付内容
- **独立路由** `/admin`（也认 `#/admin`），刷新直达；极简路由不引 react-router；非管理员访问静默回工作台。
- **四个板块**：用户与额度（列表/搜索/充值/流水+金额）、用量概览（6 指标卡 + 近 7/14/30 天消耗条形图）、任务监控（全局任务+状态筛选+暂停原因）、系统状态（mysql/redis/chroma + 模型清单）。
- **后端**：`GET /admin/overview`、`GET /admin/usage?days=`、`GET /admin/tasks?status=`；迁移 `0009_ledger_amount`（充值金额，存量 NULL 不计入，不臆造）；`TokenPool.credit` 落 amount。
- **口径**：本月消耗只计 `kind=task` 的 settle；累计充值只计有 amount 的充值行。

### 验证状态
- ✅ pytest 262 / jest 40 / vitest 73；tsc 无错。
- ✅ 真机：overview（2 用户 / 余额 5.5w / 本月 40.4w / 暂停 3）、usage 4 桶、tasks 30 条含暂停原因；充值 7000 → recharge_total=7000。
- ✅ Playwright 截图四板块布局正常；`/admin` 直达标题「管理端」；点入口 URL 正确切换。

---

## v1.0.0-p6.25 — 管理端最小版 + 多原因暂停续跑（2026-10-23）

**类型**：功能（两个 P0 断点）
**Tag 提交**：见 `git show v1.0.0-p6.25`

### 交付内容
- **多原因暂停**：`core/runs.py` 运行登记（run_id→Event+owner）+ 协作式取消（ReAct 每步前、DAG 每层/每子任务前检查）→ `RunCancelled` 一路收尾为 `paused_user`；任务行记 `pause_reason/pause_payload`。
  - `quota`（余额不足，原有 interrupt 路径）→ 充值后继续，零成本；
  - `user`（用户点停止）→ 步骤边界停下，可继续；
  - `error`（中途报错）→ 由"失败终态"改为可恢复的 `paused_error`，保留原文可重试；
  - `input`（等用户补充信息）/`permission`（审批门）→ 枚举预留，未实现。
- **续跑/重试**：`POST /tasks/{id}/resume` 按 `request_json`（text/attachments/model/effort）重跑，新任务 `retry_of` 指回原任务、原任务标 `resumed`；`GET /tasks/{id}` 与 `GET /tasks?status=` 供前端恢复横幅。
- **管理端**：`GET /admin/users`（含余额、搜索）、`POST /admin/users/{id}/recharge`（1~1000万，钱包 upsert + `kind=recharge` 账本 + 操作人）、`GET /admin/users/{id}/ledger`。权限双闸：网关 `JwtAuthGuard` 前缀+角色，后端 `_require_admin` 权威校验。
- **数据**：迁移 `0008_pause_and_recharge`（task 四列 + ledger kind/note）；`/quota` 流水带回 kind/note。
- **前端**：侧栏「⚙ 管理」入口（仅管理员）→ 管理页（列表/充值/流水）；暂停横幅（原因+继续/暂不）；停止按钮改为"通知后端暂停"。
- **结算纪律**：取消/报错按预扣额结算（不退），防"发起即暂停"套退款；`tokens_used` 同步记录。

### 验证状态
- ✅ 三套全绿：pytest 262 / jest 40 / vitest 67（tsc 无错）。
- ✅ 真实全栈：普通用户 403；充值 10000 到账 + 账本 note 含操作人；用户暂停 → `paused_user` → 续跑 `done`（retry_of 正确、tokens 22170）；余额 100 → `paused_insufficient_quota`（payload 余额/缺额）→ 充值 50000 → 续跑成功 5019 tokens 入账。
- 手动验证：`docs/手动验证-p6.25-管理端与暂停续跑.md`（7 组用例，预期值实测）。

### 已知遗留
- 续跑为"重跑式"（非断点续跑）：MemorySaver 跨重启失效；持久化 checkpoint 留后续。
- 取消信号进程内（单实例）；多副本需换 Redis。
- 预留未做：`input`（暂停等补充信息）、`permission`（审批门）。

---

## v1.0.0-p4.3d — 子任务带上用户请求 + 护栏停止后强制收尾（2026-10-23）

**类型**：修复（p4.3 收尾，真跑验证驱动）
**Tag 提交**：见 `git show v1.0.0-p4.3d`

### 交付内容
- 子任务文本带上**用户完整请求**（截断 6000 字）+ 本步分工限定——此前只有"analysis 任务"四个字，模型不知道要分析什么，只能反问。
- `run_react` 增加 `synthesize`：重复调用/无效工具名/超步数三条护栏停止路径，先把已有观察收尾成人话再交给用户；收尾失败如实回落原文。收尾用量并入 token 账。
- 手动验证文档：`docs/手动验证-p4.3-DAG结果传递与并行.md`（9 组用例，预期值全部来自实测）。

### 验证状态
- ✅ pytest 236 passed / 3 skipped；真 LLM 三段链（clean_id 贯穿、数字对账 4350.50/2580.00/6930.50、报表 artifact、tokens 26009）；真 LLM 并行（rag∥cleaning 交错、seq 唯一、tokens 11727）。

### 已知遗留
- 配额暂停无 HTTP 续跑入口；无管理端充值（余额耗尽只能手工改库）；RAG 侧检索 502（RAG 项目自身问题）。

---

## v1.0.0-p4.3 — DAG 结果传递 + 层内并行 + multi token 汇总（2026-10-23）

**类型**：功能（Phase 4 补齐：p4.1 遗留项落地）
**Tag 提交**：见 `git show v1.0.0-p4.3`
**分刀 tag**：`v1.0.0-p4.3a`（结果传递）→ `v1.0.0-p4.3b`（层内并行 + seq 线程安全）→ `v1.0.0-p4.3c`（token 汇总 + 并行度配置）

### 交付内容
- **结果传递**：`run_dag` 把直接上游 `AgentResult` 交给子任务 runner；`compose_subtask_text` 拼「intent + 上游摘要」（单上游截断 2000 字；上游 `hit_cap` 如实标注"未完成"）——「先清洗再分析」不再盲跑。
- **层内并行**：同层无依赖子任务 `ThreadPoolExecutor` 并行（`DAG_MAX_CONCURRENCY` 默认 3，1=串行回落）；`EventSequence` 加锁保证并发 seq 不重复；结果按子任务序重建，汇总文本确定。
- **multi token 汇总**：`AgentResult.tokens_used` + `multi_node` 汇总——修复 multi 路由 settle `actual=0` 全额退回的账目破洞（真跑验证 3 子任务 15577 tokens 如实入账）。
- **顺带修复（真跑冒烟抓到）**：非流式 brain 漏 p6.3 混合策略——模型输出协议 B 的自然语言终答时，非流式路径当"无法解析"直接停掉；两条路径判定一致后 multi 并行子任务恢复正常产出。
- **取舍**：multi 子任务块状推送思考/终答（并行下避免多 Agent 字符级交错）；单 Agent 路径逐字流不变。

### 验证状态
- ✅ pytest 229 passed / vitest 64 / jest 36 三套全绿；三轮真 LLM 冒烟（结果链完整、并行 seq 唯一连续、token 如实入账）。

### 已知遗留
- 多 Agent 并行态前端可视化（delta 事件带 subtask_id 归属 + 分 Agent 打字机）——独立迭代，不在本范围。

---

## v1.0.0-p6.24c — 扫描识别读不到字时再试一次（2026-10-22）

**类型**：修复
**Tag 提交**：见 `git show v1.0.0-p6.24c`

### 交付内容
- 识别结果里没有足够文字时再请求一次。图片和扫描版 PDF 都能读出「锅圈食汇上海店实付128.50元」。

---

## v1.0.0-p6.24b — 扫描识别改用 Free OCR 提示（2026-10-22）

**类型**：修复
**Tag 提交**：见 `git show v1.0.0-p6.24b`

### 交付内容
- DeepSeek-OCR 需要 `<image>\nFree OCR.` 才会输出文字。上一版提示返回的是视觉记号，读不到「锅圈食汇 实付 128.50 元」。

---

## v1.0.0-p6.24 — 扫描识别、短期记忆和上下文用量（2026-10-22）

**类型**：功能
**Tag 提交**：见 `git show v1.0.0-p6.24`

### 交付内容
- 图片和没有可用文字层的 PDF，交给 DeepSeek-OCR 转成文字。有文字层的 PDF 仍直接抽文字。
- 最近 4 轮对话原样保留，更早的压成摘要。出现「这个、刚才」等指代时，只按这段上下文消解。
- 会话标题旁有上下文环。点开可看系统提示、工具说明、规则、历史摘要、近期对话和本轮问题各占多少。

### 验证状态
- ✅ 记忆切分、文字版 PDF 不走识别、扫描版 PDF 走识别，以及编排流测试通过。

---

## v1.0.0-p6.23 — 会话操作改为点击，删除用弹窗确认（2026-10-22）

**类型**：体验
**Tag 提交**：见 `git show v1.0.0-p6.23`

### 交付内容
- 会话右侧图标点击后展开操作。悬停只提示「更多操作」。
- 置顶、重命名、删除都是图标加文字。删除弹出确认框，取消不删。

### 验证状态
- ✅ 侧栏测试：未点击时没有菜单；确认删除后才调用删除。

---

## v1.0.0-p6.22 — 报表观察不再被掏空，会话可置顶重命名删除（2026-10-22）

**类型**：修复 / 体验
**Tag 提交**：见 `git show v1.0.0-p6.22`

### 交付内容
- 工具返回的报表和数字会进入下一步观察。相同参数不会反复调用。有了报表就直接写分析和建议。
- 会话悬停时，时间换成操作图标。图标上展开置顶、重命名、删除。名称超出时左右循环滚动。

### 验证状态
- ✅ 报表摘要、重复调用拦截、会话接口和侧栏菜单测试通过。

---

## v1.0.0-p6.21 — 模型只标思考与视觉，销售报表缺项不算完成（2026-10-22）

**类型**：功能 / 体验
**Tag 提交**：见 `git show v1.0.0-p6.21`

### 交付内容
- LongCat-2.0、Hy4-preview、Qwen3.5-9B 的能力只保留思考和视觉。参数规模、工具、续写等标签不再出现在模型列表。
- `sales_report` 生成锅圈销售报表。时间范围、指标、口径、数据来源缺一项时 `complete` 为 false。数字只来自 `query_orders`。

### 验证状态
- ✅ 报表缺项、上海 1 月实付、排除已取消，以及 Agent 白名单测试通过。模型标签测试通过。

---

## v1.0.0-p6.20 — 补齐模型能力并具名查订单（2026-10-22）

**类型**：功能 / 配置
**Tag 提交**：见 `git show v1.0.0-p6.20`

### 交付内容
- LongCat-2.0、Hy4-preview 标为推理模型，并带上参数规模、工具、续写、长文本等标签。Qwen3.5-9B 标为推理、工具和视觉，上下文仍是 256K。
- `query_orders` 按时间、城市、门店、渠道、状态和分组查锅圈订单。SQL 不交给模型。空表会从英文表头 CSV 导入 500 条。不返回手机号、真实姓名和收货地址。

### 验证状态
- ✅ 订单查询、Agent 白名单、模型注册表和迁移表名测试 23 passed。模型标签测试 2 passed。

---

## v1.0.0-p6.19b — 官方模型上下文仍显示 128K（2026-10-22）

**类型**：修复
**Tag 提交**：见 `git show v1.0.0-p6.19b`

### 交付内容
- 128000 同时能被 1000 和 1024 整除，上一版把它显示成了 125K。能被 1000 整除的仍按千位显示，所以官方 V3 / R1 回到 128K。硅基的 160K、256K、1M 不变。

---

## v1.0.0-p6.19 — 锅圈图标、思考耗时与硅基模型（2026-10-22）

**类型**：体验 / 配置
**Tag 提交**：见 `git show v1.0.0-p6.19`

### 交付内容
- 侧栏和浏览器标签使用锅圈 logo，与 RAG 项目同一份图。
- 每一段深度思考的耗时紧跟在「深度思考」后面，字数仍在右侧。
- 硅基流动补上 LongCat-2.0、Hy4-preview、DeepSeek V4-Pro、Qwen3.8-27B。GLM-5.3-Flash 标为思考和视觉，Qwen3.5-9B 改为 256K，硅基 DeepSeek V3 / R1 改为 160K。
- DeepSeek-OCR 不进对话列表。8K 上下文只适合扫描件识别那一步，记在待办里。

### 验证状态
- ✅ 前端过程、消息和侧栏测试通过。模型注册表测试通过。

---

## v1.0.0-p6.18 — SQL 兜底护栏与按顺序展示过程（2026-10-22）

**类型**：功能 / 体验
**Tag 提交**：见 `git show v1.0.0-p6.18`

### 交付内容
- `db_query` 仍是没有专用查询时的兜底。必须带 WHERE、GROUP BY 或聚合，最多 50 行，并加上 3 秒执行上限。限制写在工具里，提示词只说明何时才用它。
- 回复分成两层：上面是可展开的过程（思考、阶段回答、工具按发生顺序），下面才是最后一段总结。每一段思考单独展开，固定高度滚动。

### 验证状态
- ✅ SQL 护栏与 Agent 提示词测试 21 passed。前端过程切段与消息展示 25 passed。

---

## v1.0.0-p6.17 — 按清洗表生成图表（2026-10-22）

**类型**：功能（render_chart）
**Tag 提交**：见 `git show v1.0.0-p6.17`

### 交付内容
- 用 Matplotlib 画 bar、barh、line、area、pie、scatter、heatmap、hist。数字只来自 `clean_id`，模型不能传数据点。
- 导出 SVG。文字保留为字符，中文在预览时由浏览器字体显示。
- 文件仍在 `upload/<用户>/_out/`。生成文档和图表都会写入 `asset` 表（用户、任务、相对路径）。
- 回复里的「生成文件」可预览 SVG。

### 验证状态
- ✅ 柱状、折线、饼图、热力、散点、直方图测试通过；饼图拒绝负数；asset 写入用户和路径。

---

## v1.0.0-p6.16 — 把结论写成 md 或 docx（2026-10-22）

**类型**：功能（write_document）
**Tag 提交**：见 `git show v1.0.0-p6.16`

### 交付内容
- `write_document` 把已有结论写成 md 或 docx，放在当前用户目录的 `_out/`。不生成表格文件，也不画图。
- 传入 `clean_id` 时，文末写上原文件、列和清洗后行数。编号不存在就不写文件。
- 回复下方出现「生成文件」，点击后预览服务器上的那一份。

### 验证状态
- ✅ `test_tools_write.py` 与生成文件预览共 5 passed；前端生成文件按钮测试通过。

---

## v1.0.0-p6.15 — 上传表格先清洗再分析（2026-10-22）

**类型**：功能（clean_table / analyze_table）
**Tag 提交**：见 `git show v1.0.0-p6.15`

### 交付内容
- `clean_table` 清洗 csv、xlsx 和对象数组 json，不改原文件。去掉全空行、全空列、重复表头和完全相同的行；`null`、`N/A`、`无`、`-` 视为空。
- 指定关键列时，该列为空的行剔除并计数。未指定则不猜、不删，只报告每列缺失。不填补缺失，不因异常值删行。不能当数字的格子在求和时跳过，结果用空而不是 0。
- `analyze_table` 只接受清洗返回的 `clean_id`，可过滤、分组和汇总。

### 验证状态
- ✅ `test_tools_table.py` 6 passed，`test_agents.py` 与文档读取测试一并 30 passed。

---

## v1.0.0-p6.14 — 读取 docx、csv、xlsx、json（2026-10-22）

**类型**：功能（read_document 阅读器）
**Tag 提交**：见 `git show v1.0.0-p6.14`

### 交付内容
- 同一个 `read_document` 增加 docx、csv、xlsx、json。上传白名单与预览跟着放开。
- 表格只返回表头、数据行数和前 20 行，并写明总行数。json 能解析就格式化；不能解析就说明不是合法 JSON，并附上原文。
- 点开这类文件时，预览显示抽出的文本，不把压缩包原样塞进页面。

### 验证状态
- ✅ `test_tools_doc.py` 与 `test_documents.py` 共 27 passed。

---

## v1.0.0-p6.13 — 对话体验、账号与按用户读文件（2026-10-22）

**类型**：功能（输入条、个人中心、改密、附件预览、读文件目录）
**Tag 提交**：见 `git show v1.0.0-p6.13`

### 交付内容
- 输入条换成 PromptBar，接上发送、停止、上传、模型和三档力度。力度按模型真实档位折叠后再传给接口。
- 侧栏显示项目简介和版本。用户消息悬停可编辑、复制；回复下方固定显示复制、赞踩、用量、模型、时间和耗时。
- 个人中心：资料、剩余额度、本月和累计用量。点剩余额度查看消耗明细（时间、模型、用量）。退出登录为左图标加文字、右图标，并需再确认一次。
- 修改密码后提高 token_version，旧登录态失效。
- 气泡在正文下标明「附带文件」。点文件名预览服务器上的那一份。
- `read_document` 只在当前登录用户的上传目录里找文件。只传文件名，或带上用户名目录，都能读到。

### 验证状态
- ✅ 后端 pytest 174 passed / 3 skipped；前端 vitest 56 passed；网关改密测试 8 passed。
- ✅ 浏览器核对消耗明细、退出确认和文件预览。

---

## v1.0.0-p6.10 — 打字机队列 + 复制/编辑 + 用量明细（2026-10-21）

**类型**：体验/功能补全（用户四问：token 消耗/用量入库/复制编辑/打字机渲染）
**Tag 提交**：见 `git show v1.0.0-p6.10`

### 交付内容
- **用量明细**：侧栏余额徽章点击展开最近 8 笔流水（token_ledger 数据 p6.4 已入库，本轮只补前端展示）。
- **复制/编辑**（对齐 RAG）：user hover 编辑回填/复制；assistant hover 复制 md 原文；历史消息（trace 重建）同样可用。
- **打字机正解=缓冲队列+rAF 匀速播放**：delta 只更新 textRef 不渲染，rAF 60fps 每帧推进 `step=ceil(剩余/8)`——渲染频率与 delta 率解耦（LLM 出字 ~5ms 快于帧率 16.7ms 时"到达即渲染"必跳字）。
- **token 消耗实测**：普通 1.1-2.1K；通读 2 万字 25.1K（大 observation 多轮重复携带）。优化路径（前缀缓存/滑动窗口/同文件去重）写入文档待点单。

### 验证状态
- ✅ 前端 tsc + vitest 21 + build 全绿；后端 146 passed 无涉。
- ✅ 真链路 smoke 108 delta 正常。

---

## v1.0.0-p6.9 — 文档通读 + 打字机逐字感修复（2026-10-21）

**类型**：缺陷修复/体验（"只读到开头"+ 打字机不明显）
**Tag 提交**：见 `git show v1.0.0-p6.9`

### 交付内容
- **文档截断四层链路全放大**：read_document 8000→50000 / _summarize_observation 1200→24000 / brain._render_history **400→24000（最后一层瓶颈，p4.1 遗留）** / 前端 500→2000。实测 LLM 答出 2 万字文档最后一章标题。
- **打字机**：后端 delta 本就 5ms 级，真凶=前端 MarkdownView 80ms 渲染节流合并——改自适应（短文本每 delta 直渲），后由 p6.10 队列方案统一取代。
- 顺手发现钱包 settle 穿 0 bug（→ p6.11 修复）。

### 验证状态
- ✅ pytest 146 passed / 3 skipped（observation 摘要断言改"2 万字不截断、6 万字截断"双口径）。

---

## v1.0.0-p6.8 — 模型列表重构 + 模型信息展示（2026-10-21，含 p6.8b 参数修正）

**类型**：功能/体验（模型注册表重构）
**Tag 提交**：见 `git show v1.0.0-p6.8` / `git show v1.0.0-p6.8b`

### 交付内容
- 默认模型=deepseek-chat（DeepSeek 官方 V3）；8 个对话模型按渠道 optgroup 分组：DeepSeek 官方（chat/reasoner）+ 硅基流动（V3/R1/V4.1-Flash 1M 思考·视觉/V4-Flash/GLM-5.3-Flash/Qwen3.5-9B），名字不带 org 前缀；下线 qwen-plus/glm-4/kimi。
- ModelEntry.description + /models 返回 + 前端下拉信息条。
- **p6.8b 修正**（用户按硅基流动模型页纠正）：GLM-5.3-Flash 128K→1M；V4-Flash 262K+视觉→1M 无视觉；V3(sf)/R1(sf) 65K→128K。
- 坑：config 卷改 yaml ≠ 生效——load_registry 有 lru_cache，需 `docker compose restart backend`。

### 验证状态
- ✅ pytest 146 passed / 3 skipped；V4.1-Flash 真调通过（126 tokens）。
- ✅ /models 硅基流动组 1M/131K 全部正确。

---

## v1.0.0-p6.12c — 时间时区修复 + 会话列表分页展开 + 滚动条贴边（2026-10-21）

**类型**：缺陷修复（时间差 8h）+ 体验（分页展开/滚动条）
**Tag 提交**：见 `git show v1.0.0-p6.12c`

### 交付内容
- **时间差 8 小时**：库内存 UTC、接口裸字符串无时区，前端按本地解析差 8h。修：`_iso_utc` 统一输出带 `Z` 的 ISO（sessions created_at/updated_at、messages created_at），存储保持 UTC，前端 Date 自动转本地。线上验证 `2026-10-21T13:40:13.380547Z`。
- **会话列表分页展开**：默认 10 条，"查看更多 (剩余N)" 每次加载下一条 10 条；未完显示 `查看更多 (N) | 收起`，全部展示完只剩 `收起`。
- **滚动条贴边**：`.session-list` 负 margin 抵消侧栏右 padding，滚动条紧贴侧栏最右缘，内容 padding 让位。

### 验证状态
- ✅ pytest 160 passed（+1）/ 前端 tsc / vitest 36（+2）/ build 全绿；容器已重建。

---

## v1.0.0-p6.12b — 失败/暂停专门展示 + 附件 chip 入框 + 余额数据修复（2026-10-21）

**类型**：缺陷修复（失败不可见）+ 体验（附件 chip 位置）
**Tag 提交**：见 `git show v1.0.0-p6.12b`

### 交付内容
- **失败专门展示**：deriveFailure 归一 quota_paused/error/done(paused_*)，ChatMessage 渲染专用失败块（quota 橙/error 红，持久化随消息固化）——修"余额暂停后界面毫无反馈"（旧实现只有流式临时 banner，done 后 reset 即消失）。
- **余额脏数据**：dev 账号 -37798（p6.11 前历史遗留）→ 重置 100000，/quota 验证通过；p6.11 下限保护已随容器生效。
- **附件 chip**：移入输入条内部（控件行上方），hover 显示完整引用路径；说明引用逻辑（路径经 /tasks attachments → 后端 prompt 前缀注入，无需把路径写成文本）。
- **容器重建**：前端/后端镜像更新（p6.11+p6.12+p6.12b 全部生效到 8080/3001）。

### 验证状态
- ✅ 前端 tsc / vitest 34（+4）/ build 全绿；后端 159 维持。
- ✅ 六容器 healthy；/health ok；登录 → /quota balance=100000。

---

## v1.0.0-p6.12 — 附件引用闭环 + 会话列表体验修复（2026-10-21）

**类型**：功能补全 + 缺陷修复（附件 chip/拖拽注入；会话时间 bug；列表折叠）
**Tag 提交**：见 `git show v1.0.0-p6.12`

### 交付内容
- **附件引用闭环**：上传成功进输入条上方附件 chip（可移除）；拖拽文件到输入条即上传；发送时 attachments 随 `/tasks` 消息，后端 fail-closed 校验（限本人目录内且存在，防穿越/越权）后以 prompt 前缀注入；附件列表存 user 消息 trace，历史重建渲染 chip。
- **会话时间 bug**：后端 list_sessions 返回 updated_at=最后一条消息时间（无消息回落 created_at）并按其倒序；前端不再用 Date.now() 覆盖。
- **相对时间规则**：1 分钟内 HH:MM → XX分钟前 → XX小时前 → XX天前 → 超 7 天 M月D日。
- **列表折叠**：默认 10 条，超出显示"查看更多 (N)"（N=全部条数），点击展开全部。

### 验证状态
- ✅ pytest 159 passed / 3 skipped（+10：updated_at 排序回落、附件穿越/越权/缺失拒绝、前缀组装）。
- ✅ 前端 tsc 零错误 / vitest 30 passed（+9）/ build 通过。

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

---

## v1.0.0-p6.47 — 表格过滤补 in/not_in + CI 手册补离线下载（2026-10-26）

**类型**：功能 + 文档

- `analyze_table` / `render_chart` 的 filters 补 `in` / `not_in`（value 接受列表或逗号/顿号分隔串）——
  "分组统计里只挑特定值再画图"（如 9 月 vs 10 月对比）不再逼模型绕路。与 query_orders 的过滤口径对齐。
- CI 手册：runner 版本落成 2.337.0（与服务器已装一致），补"本地开代理下载 → scp 上传"的离线安装路径。

---

## v1.0.0-p6.48 — 前端三处体验修复（2026-10-26）

**类型**：修复 + 功能

- 切换会话不再闪"有什么可以帮你"空态：拉取消息期间隐藏欢迎页（loadingSession）。
- 网站标题改为「锅圈企业级智能办公助手」。
- 图表卡片右上角新增「下载 PNG」按钮（悬浮出现）：echarts canvas getDataURL 白底 2x 导出，文件名取图表标题。

**本版为 CI 接通后首个走全自动部署的版本。**

---

## v2.0.0-p2.6 — OOM 事故复盘与自愈加固（2026-10-28）

**类型**：稳定性（生产事故修复）

- 事故：backend 内存涨到 1.8GB 被内核 OOM 击杀（05:12），且 restart 策略为 no，躺尸 10 小时全站不可用。
- 根修：`ping_chroma` 每次新建 `chromadb.HttpClient` 且不关闭——httpx 连接池随 /health、/admin/overview 调用线性泄漏（socket 1013 个、RSS 1.8GB）。改为模块级单例 + 失败自愈重建。
- 自愈：office 三容器 `restart: unless-stopped`（此前 no）；日志轮转 max-size 10m×3（磁盘已 79%）。
- 观测：health 新增 `rss_mb`（当前值），与 open_fds 一起构成资源水位看板。
- 全量 pytest 438 passed / 3 skipped。部署验证：restart 策略生效、health ok、fds 19、rss 125MB。

---

## v2.0.0-p2.5 — 管理端尺寸对齐 rag admin-console（2026-10-27）
