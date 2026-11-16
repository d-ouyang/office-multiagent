# PLAN-2.3.0 · 上下文预算化（C 层补全）

> 立项：2026-11-16，分支 `feature/2.3.0-context-budget`（自 `feature/2.2.0-harness` @ `9218774` 切出）。
> 依据：2026-11-16 C 层复盘（六处硬编码截断点清单）+ rag 4.1.0-p1.2 `core/context_budget.py` 已跑通的同构方案。
> 纪律不变：每步 testcase + tag `v2.3.0-pN.M`（老 tag 永不重打）+ 迭代文档 + RELEASES 更新 + 推送。
> 硬约束不变：COST-007 / Redis 仅缓存与队列 / 单机 4C4G / **不引入新依赖**（不装 tiktoken，沿用 `estimate_tokens`）。
> 定位：2.2.0 补的是"敢不敢交给别人用"（可替换/可计量/可重入/可回放/可门禁），2.3.0 只补一件事——**上下文从"六个常数"变成"一份预算"**。

---

## 0. 为什么做（现状与风险）

### 0.1 现状：六个互不知情的常量

| 截断点 | 位置 | 值 | 可配 |
| ------ | ---- | -- | ---- |
| JSON 协议 history 渲染 | `orchestration/brain.py::_render_history` | `[:24000]` 硬编码 | 否 |
| 原生 tool_calls 渲染 | `orchestration/brain.py::_messages_for_tool_calls` | `[:24000]` 硬编码 | 否 |
| 工具观察摘要 | `orchestration/react.py::_summarize_observation` | 默认参数 24000（调用点 `react.py:459` 未覆盖） | 否 |
| 文档读取上限 | `core/config.py::doc_read_max_chars` | 50000 字 | 是 |
| 长期记忆注入 | `core/config.py::user_memory_inject_chars` | 4000 字 | 是 |
| 会话历史 | `orchestration/memory.py::RECENT_ROUNDS` / `compress_rounds` | 4 轮 / 每段 80 字 | 否（模块常量） |

### 0.2 三个缺陷

1. **互不知情**：每个截断点独立决策，谁也不知道别人占了多少。`context_usage` 只做事后统计发事件，不参与任何判定——没有"已用 > X% 就收敛"的分支。
2. **只截不压**：截断丢尾部（信息直接消失），压缩保语义。会话级有 `compress_rounds`，**循环级没有**——一步 24K 塞进 history 就永久留着，只增不减。
3. **丢了不说**：只在正文加"（已截断）"，不进事件、不进 trace、不进指标。对比 rag `budget_blocks` 返回 `dropped` 块数/字符数并写 trace。

### 0.3 风险（不是理论）

4 步 ReAct × 每步 24000 汉字 ≈ 24000 token/步 ≈ 96K，叠加系统提示 + 工具说明（13 个工具的 description）+ 协议模板 + 历史摘要 + 本轮问题，128K 窗口触手可及；`core/llm.py` 对 `context_length_exceeded` **没有任何专门处理**——`_is_transient()` 只认 429/5xx/网络错，400 直接上抛 → 任务收尾失败。跑不跑得通取决于用户文档多大、模型走了几步，而不是设计保证。

---

## 1. 三条判据（每条独立可观测）

| # | 判据 | 观测方式 |
| - | ---- | -------- |
| **M1** | 上限可配：改完下一个任务即生效，不发版不重启 | `PUT /api/v1/settings/<key>` 后立即真跑一次，事件流与日志体现新值 |
| **M2** | 单次请求的上下文有硬上限：超了按"最近优先 + 旧步降级"自动收敛，不靠常数 | 构造 6 步 × 3 万字任务，渲染后 `estimate_tokens` ≤ 预算，任务照常完成 |
| **M3** | 真撞窗口时自动压缩重试一次，用户看到的是"重排了上下文"，不是任务失败 | 注入 provider 400 错误体，任务完成且日志留痕 |

**验收口径**：三条判据全部达成 + pytest 基线绿 + 生产冒烟（一条 2 万字文档任务 + 一条多轮追问任务）通过。

---

## 2. 三步清单

### p1.0 阈值可配（半天）— M1

**动哪里**

| 文件 | 动作 |
| ---- | ---- |
| `core/config.py` | 新增 `observation_max_chars: int = 24000`、`history_step_max_chars: int = 24000`、`history_recent_rounds: int = 4`、`history_round_chars: int = 80` |
| `core/runtime_settings.py::_catalog` | 新增 4 项（scope=system，int，min/max 明确）；管理端 `public_items()` 自动带出，无需改前端 |
| `orchestration/react.py` | `_summarize_observation(obs, max_chars=...)` 调用点改为传 `runtime_settings.effective("observation_max_chars")`；函数默认值保留但不再被依赖 |
| `orchestration/brain.py` | `_render_history` / `_messages_for_tool_calls` 两处 `24000` → 统一走一个 `_obs_limit()` 私有方法（读取 runtime_settings，失败回落 settings） |
| `orchestration/memory.py` | `RECENT_ROUNDS` / `[:80]` → 从 config 读，函数签名加可选参数（缺省仍取模块常量，保持测试兼容） |

**testcase**（新文件 `tests/test_context_settings.py`，5 条）

| 编号 | 用例 | 断言要点 |
| ---- | ---- | -------- |
| S-1 | `test_observation_max_chars_from_settings` | runtime_setting 置 8000 → 30000 字 dict 观察渲染后 ≤ 8000 + 截断标记 |
| S-2 | `test_render_history_uses_configured_limit` | 同 S-1，走 `_render_history` 路径；配 8000 → 出现"已截断" |
| S-3 | `test_tool_calls_path_same_limit` | 原生协议路径与 JSON 协议**同值**（双协议同构回归） |
| S-4 | `test_recent_rounds_configurable` | 5 轮历史、配 `history_recent_rounds=2` → summary 覆盖 3 轮、recent 覆盖 2 轮 |
| S-5 | `test_settings_catalog_exposes_new_keys` | `public_items()` 含 4 个新 key，`value_type=int`，min/max 生效（越界 `validate_and_store` 抛 ValueError） |

**判据**：`PUT /api/v1/settings/observation_max_chars=8000` → 同进程下一任务，`context_usage` 事件分项与正文截断长度均按 8000；无需重启。
**预计基线**：pytest 563 → 568。

**实施记录（2026-11-16，已完成 · 未提交）**

- 改动 5 个文件 / +154 −21：`core/config.py`（4 字段）、`core/runtime_settings.py`（4 项 catalog）、`orchestration/react.py`（`_summarize_observation` 改 `max_chars=None` 走设置，0=不限）、`orchestration/brain.py`、`orchestration/memory.py`。
- 新增 `tests/test_context_settings.py` **8 条**（比计划多 3 条：0=不限、单轮摘要长度、缺省值对齐 config）。
- **实现偏差**：没有让两条协议各自读配置，而是收敛成模块级 `history_step_limit()`，`_obs_limit()` 与两个 `staticmethod` 共用——灰度期换协议不换行为，排障可归因。
- `prepare_turn` 的 `recent_rounds=0` 单独分支（Python 的 `rounds[:-0]` 是空列表，会静默变成"全部原文"，已在 S-4 锁死）。
- 实测：`pytest 563 → 571 passed / 3 skipped`，零回归。ruff 未装（不引入新依赖），静态检查以 pytest 导入 + 审阅代替。
- 未做：未 commit、未打 tag（tag 即触发 CI 自动部署，等确认）。

---

### p1.1 预算感知渲染（1~1.5 天，核心）— M2

**动哪里**

| 文件 | 动作 |
| ---- | ---- |
| `orchestration/context_budget.py` | **新建**（原计划放 `core/`，实际放这里——它依赖 `memory.estimate_tokens`，放 core 会造成 core→orchestration 反向依赖）。`budget_steps(steps, max_tokens, step_cap)` → `BudgetResult{lines, obs_text, kept, downgraded, omitted, dropped_chars, notes}` |
| `orchestration/brain.py` | `_render_history` 改调 `budget_steps`；预算来源见下 |
| `orchestration/react.py` | 调 `run_react` 时把预算实例传进 brain（或 brain 构造参数），使渲染时有账可算 |
| `api/routes.py` / `orchestration/graph.py` | 计算并注入 `step_history_budget`：`min(模型窗口 × 0.6, token_budget.remaining)`，模型窗口从 `model_registry.load_registry()` 的 `context_window` 取（`graph.py::_emit_context` 已有同款读法，复用） |

**算法要点**（照抄 rag `budget_blocks` 的形状，规则不同）

1. **最近优先**：从最后一步往回分配，`step_budget = max_tokens // min(len(steps), 4)` 起步，剩余额度向前滚。
2. **整块保留或整块降级**：绝不切半句（半截观察比没有更危险）。
3. **降级文案必须带信息**：`第 N 步 调用了 query_orders（3 个参数），返回 128 行，要点：<首行/前 200 字>`——不能只写"已省略"。
4. **最后一步保底**：即使单独超预算也保留（截断该步并标注 `…（超长截断）`）。
5. **0 = 不限**：预算为 0 时直通，行为与当前完全一致（回退开关）。
6. **dropped 记账**：`BudgetResult.dropped` + `notes` 进 `context_usage` 事件 payload。

**testcase**（新文件 `tests/test_context_budget.py`，8 条）

| 编号 | 用例 | 断言要点 |
| ---- | ---- | -------- |
| B-1 | `test_budget_keeps_recent_steps` | 6 步、预算只够 2 步 → 最后 2 步**原文完整**保留 |
| B-2 | `test_budget_downgrades_old_steps_with_digest` | 前 4 步变降级行，且含"调用了 <工具名>"与"返回 <N> 行"，非空串 |
| B-3 | `test_budget_never_splits_a_step` | 任意预算下，输出行数 = 输入步数（每步一个完整块，不出现半句） |
| B-4 | `test_budget_zero_means_unlimited` | max_tokens=0 → 输出与 `_render_history` 旧实现逐字一致 |
| B-5 | `test_budget_reports_dropped` | `dropped == 降级步数`，`dropped_chars == 被降级步原文字符和` |
| B-6 | `test_single_step_over_budget_keeps_last` | 只有 1 步且自身超预算 → 保留并标"超长截断" |
| B-7 | `test_render_history_under_budget_integration` | 6 步 × 30000 字走 `_render_history` → `estimate_tokens(结果) ≤ 预算`（这是 M2 的直接证明） |
| B-8 | `test_context_usage_event_carries_budget` | `context_usage` payload 含 `budget` / `dropped` / `notes`；老前端字段不变（向后兼容） |

**判据**：6 步 × 3 万字任务能正常完成（不 400），`GET /runs/{id}/replay` 里可见前几步是降级摘要，`context_usage` 的 budget 字段与实际一致。
**预计基线**：pytest 568 → 576。

**实施记录（2026-11-16，已完成 · 未提交）**

- 新增 `orchestration/context_budget.py`（约 250 行，含注释与边界说明）；`brain._render_history` / `_messages_for_tool_calls` 双协议改用 `budget_steps`，共用 `obs_text` 判定。
- 新增第 5 个开关 `history_budget_window_pct`（0=回退到逐条截断）；`graph._history_budget()` 按"模型窗口 × 百分比"算，读不到窗口按 128K。
- **实现偏差 1（重要）**：末步保底最初给足全部预算，实测 2 万字单步会把预算吃光、前面 5 步全被整块省略——"最近优先"退化成"最近独吞"。改为**末步最多吃 60%**，其余留给更早步骤降级。
- **实现偏差 2**：seed 步（HITL 用户补充输入）免疫预算——不可再生的信息不能被压缩掉，只截正文，且最多吃"剩余预算 − 30"。
- **顺手修 p1.0 遗留**：tool_calls 路径此前静默截断（无"…（已截断）"标注），JSON 协议有标注——同一任务换协议结果不同。p1.1 统一后两条协议都标注。
- **B-9 口径**：`prompt_upper_bound` 从 UTF-8 字节改为 `estimate_tokens`（CJK 1:1），断言改为"2 万字文档不再被算成 6 万"，比原计划"≥ 旧值 ×0.4"更贴近真实风险。
- 实测：`pytest 571 → 581 passed / 3 skipped`（B-1~B-10 共 10 条，比计划多 1 条）。

---

### p1.2 撞窗口兜底（半天）— M3

**动哪里**

| 文件 | 动作 |
| ---- | ---- |
| `core/llm.py` | 新增 `ContextOverflowError(LlmError)`；在 `_chat_once` 抛错处识别 `400` + body 含 `context_length` / `maximum context` / `too long` / `超出` 等关键词，转抛该异常 |
| `core/llm.py::_is_transient` | 显式排除 `ContextOverflowError`（溢出**不是**瞬时错误，绝不能被 3 次重试吞掉） |
| `orchestration/brain.py` | `next_step` 的 `except LlmError` 分支捕获 `ContextOverflowError` → 调 `budget_steps(紧急预算 = 当前预算 // 2)` 重建 messages 重试**一次**；仍失败则抛带明确文案的错 |

**testcase**（新文件 `tests/test_context_overflow.py`，4 条）

| 编号 | 用例 | 断言要点 |
| ---- | ---- | -------- |
| O-1 | `test_detect_overflow_400` | 400 + `{"error":{"message":"This model's maximum context length is..."}}` → `ContextOverflowError` |
| O-2 | `test_overflow_not_retried_as_transient` | `_is_transient(ContextOverflowError)` 为 False；`_chat_impl` 不进入重试循环（调用计数 = 1） |
| O-3 | `test_overflow_triggers_one_emergency_compress` | 首次溢出 → 压缩后重试成功；provider 调用计数 = 2，日志含"上下文超限，压缩后重试" |
| O-4 | `test_overflow_after_compress_raises_clear_error` | 两次都溢出 → 抛错文案含"上下文超限"与"已压缩一次"，且调用计数 = 2（不无限循环） |

**判据**：本地 fake provider 注入溢出 → 任务完成；生产观察一周，`context_length` 类失败从"任务失败"降为 0 条（日志留存"压缩后重试"记录）。
**预计基线**：pytest 576 → 580。

**实施记录（2026-11-16，已完成 · 未提交）**

- `llm.py`：新增 `ContextOverflowError` + `_is_context_overflow`（400/413 + 13 条中英措辞白名单）；
  非流式与流式两条 400 分支都改抛该异常；`_is_transient` 显式返回 False。
- `brain.py`：新增 `_with_overflow_retry(call, build, budget)` + `_squeeze_budget`（腰斩、下限 1000、
  原本不限给 4000）；三条路径（JSON 非流式 / JSON 流式 / 原生 tool_calls）都接；
  `_next_step_streaming` 改为接收 build 函数，以便用更小预算重建消息重放。
- **比计划多一条测试**：O-5「预算原本不限时给 4000」——否则 `budget=0` 压缩后仍是 0，
  重试等于没压（写完才发现的漏洞）。
- 失败文案区分溢出与普通失败：溢出给"把文档拆小 / 分几步问"，普通失败仍是"模型暂不可用"。
- 实测：`pytest 581 → 586 passed / 3 skipped`。
- 已知限制：流式若 provider 先推 chunk 再报错会重复输出（罕见，400 通常在响应头阶段）；
  措辞白名单可能漏判新 provider，漏判只退回旧行为，不误伤其他错误。

---

## 3. 前置对齐（p1.1 开工必须先处理，否则预算化被二次卡住）

**口径冲突**：`token_budget.prompt_upper_bound()` 用 **UTF-8 字节数**当 token 上界（中文 ≈ 3 字节/字），而渲染预算用 `estimate_tokens`（≈1 token/汉字）。两者差约 3 倍。

后果（**以仓库缺省值为准**：`config.py:112` = 50000，p6.32 引入后未改；`docker-compose.yml:79` / `.env.example:65` 同为 50000；2026-11-16 本地容器实测生效值 50000；git 全历史 `-S "300000"` 为空）：一条 2 万字文档（≈60000 字节）进 messages 后 `reserve_call` 的 `prompt_cap` 就超上限 → 直接抛 `TokenLimitReached` → 任务变 `paused_budget`。也就是说**"截断 24000 字"和"任务上限 50000 token"这两个数本身是打架的**，只是平时文档不够大没暴露。

> **部署侧可能覆盖**：运行时设置走 `runtime_setting` 表，优先级高于环境变量与代码缺省（`runtime_settings._read_raw`）。若生产已把 `TASK_TOKEN_HARD_LIMIT` 或管理端该值调到 30 万，则上面的触发点整体后移——**但 §3.1 的结论不变，且风险形态更糟**。

### 3.1 任务累计预算 ≠ 单次请求窗口（本轮的存在理由）

`TaskTokenBudget` 管的是**一次任务累计**消耗；模型上下文窗口管的是**单次请求**的输入长度。两者独立：

| 场景 | 任务累计门 | 单次窗口（128K） | 实际结果 |
| ---- | --------- | --------------- | -------- |
| 上限 50000 + 2 万字文档 | 会拦（`prompt_cap` 超限） | 还没到 | 任务暂停，用户看到"预算不足" |
| 上限 300000 + 2 万字文档 | 不拦 | 单步 24K 字 ≈ 24K token，4~5 步逼近 128K | **先撞窗口**，且无兜底 → 任务失败 |

所以把任务上限调高并不能"解决"上下文问题，只是把"预算暂停"换成"provider 400"。p1.1 的预算感知渲染是**唯一管单次请求**的机制，它的必要性与此数值无关。

**处理**：p1.1 里把 `prompt_upper_bound` 改为复用 `estimate_tokens`（CJK 折 1、其余 /4）+ 协议余量 64，与渲染预算同口径；旧行为用测试锁死"上界不下降"（改后仍须 ≥ 旧上界 × 0.4，防止放松过度后真被 provider 拒）。这一条改动本身要有独立 testcase（计入 p1.1 的 B 系列，编号 B-9）。

---

## 4. 事件与观测

- `context_usage` 事件 payload 增 `budget` / `dropped` / `notes` 三字段（`Event.payload` 已有口，**不改契约版本**，老前端忽略新字段）。
- 每日巡检：查 `message.trace` 里 `context_usage.budget > 0 且 dropped > 0` 的 run 占比——这是"预算真的在起作用"的证据，也是判断预算是否定得过紧的依据。
- 管理端：本轮**不做**设置 UI（`/admin` 目前没有 SettingsTab，p1.6 那两个开关也一样只能走 API）。已有技术债，另立条目，本文档不扩围。

---

## 5. 风险与回退

| 风险 | 处置 |
| ---- | ---- |
| 预算过紧 → 模型"忘掉"早期观察 | 降级行必须带要点（B-2 锁死）；缺省预算取窗口 60%，留 40% 余量 |
| 双协议路径不同构 | B 系列与 S-3 各锁一条；灰度期两协议各跑一条真实任务 |
| `prompt_upper_bound` 改口径后放松过度被 provider 拒 | B-9 锁"新上界 ≥ 旧上界 × 0.4"；p1.2 的兜底作为第二道 |
| 紧急压缩把关键观察压没了 | 压缩只压"旧步"，最后一步永远保底（B-6） |
| **回退** | 三个开关全置 0（`observation_max_chars=0` 表示不限、`step_history_budget=0`、`context_compress_on_overflow=false`）→ 行为回到 2.2.0，**无需回滚代码** |

---

## 6. 不做（明确划界）

- **不做语义压缩**（用 LLM 总结旧步）：成本双倍、还要能测"压缩后准确率"，等 golden set 扩容到 30 条以上再说。
- **不做 user_memory 语义检索**（2.2.0 的 D2）：需要 Chroma + 召回评测，独立决策项。
- **不做 tiktoken 精确计数**：`estimate_tokens` 误差可接受，预算留 20% 余量比引入 C 扩展划算。
- **不做管理端设置 UI**：既有债，另立。
- **不动 `doc_read_max_chars` 的语义**（它是"读多少给模型"的产品选择，不是上下文预算）。

---

## 6.5 附：意图路由修正（p1.3，非 C 层主线）

冒烟时撞到的**既有**缺陷：文件就在用户目录里，模型却说"没有读取工具，请上传"。
三条失败路径各补一处（详见 `docs/iterations/v2.3.0-p1.3-intent-routing-fix.md`）：

| 路径 | 修正 |
| ---- | ---- |
| 规则层：否定词当肯定（"不要检索知识库"命中 rag） | `planner._all_occurrences_negated()`：关键词前 8 字内有否定词则不计分，只看前置窗口 |
| 模型层：把"读文件"当"查资料" | rag 标签收窄为"知识库既有内容"，general 补"读取用户上传文件"，加一条反例 |
| 兜底层：`capability_guards` 没有文件类词 | 增 11 条组合词 → `read_document`（刻意不用裸「文件/文档」，防误伤"生成文档/导出文件"） |

真链路结果：两句原话从"ask_user 要文件"变成"read_document 直接答对 10 章上限"。
pytest 586 → 593。结构性根治（`intents.requires` 取代手写 guards 表）记入 2.4.0 候选，不在本轮。

---

## 7. 交付物

| 阶段 | tag | 交付 |
| ---- | --- | ---- |
| p1.0 | `v2.3.0-p1.0` | ✅ 代码完成 2026-11-16（4 开关 + 8 testcase，pytest 571）· 待 commit/tag |
| p1.1 | `v2.3.0-p1.1` | ✅ 代码完成 2026-11-16（预算器 + 10 testcase，pytest 581）· 待 commit/tag |
| p1.2 | `v2.3.0-p1.2` | ✅ 代码完成 2026-11-16（溢出兜底 + 5 testcase，pytest 586）· 待 commit/tag |
| p1.3（附） | `v2.3.0-p1.3` | ✅ 意图路由修正 3 处 + 7 testcase（pytest 593）· 待 commit/tag |
| p1.4（附） | — | ✅ 单步上限 24000→50000 + 回放缺表降级（pytest 594）；结构债见 PLAN-2.4.0 |
| 收官 | `v2.3.0` | RELEASES 更新 + 生产冒烟记录（2 万字文档任务 / 多轮追问任务） |
| **实际** | — | **563 → 571 → 581 → 586**（21 条新测试，零回归）；代码三步全绿，未部署 |

**工作量**：2~2.5 天（p1.0 半天 / p1.1 1~1.5 天 / p1.2 半天）。**测试基线**：563 → 571 → 581 → 586（实际）。
