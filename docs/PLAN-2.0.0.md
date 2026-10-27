# PLAN-2.0.0 · 多 Agent 智能办公助手 2.0.0（可执行计划）

> 立项：2026-10-26。派生自两份输入：
> ① 《office-multiagent Tools → tool_calls 改造文档》（Cursor 共享页，用户 2026-10-26 提供）——P1 的基础，要点摘录见附录 A；
> ② 三张参考截图（反馈弹窗 / 侧边栏标题 / 对话区布局）——P2/P3/P4 的交互与视觉基准。
> 本文件回答"按什么顺序做 / 每步交付什么 / 怎么验收 / 怎么打点留痕"；沿用 `PLAN-1.0.0.md` 的版本纪律。

---

## 1. 版本纪律（沿用 1.0.0，仅版本段变更）

- Tag 格式：`v2.0.0-pN.M`（半项加字母后缀，如 `p2.1a`）；**老 tag 永不重打**。
- 每步完成五件事：① `docs/iterations/v2.0.0-pN.M-<slug>.md` ② `docs/RELEASES.md` 加对外段 ③ commit ④ tag ⑤ 更新本计划进度总览表。
- 测试基线（2026-10-26）：pytest 389 passed / 3 skipped、vitest、jest 全绿；每步 testcase 不许让存量转红。
- 涉及 DB：迁移用 `op.execute` 原生 DDL；**同步改 `db/init.sql` 并跑 `test_init_sql_columns_cover_required` 列级护栏**（生产 500 教训）；生产建库路径 = init.sql 灌库 + `alembic stamp head`。
- 发布：打 tag 推送即触发 CI 自动部署（p6.47b 已接通）。

## 2. 工作包总览

| 编号 | 工作包 | 性质 | 粒度 | 依赖 |
| --- | --- | --- | --- | --- |
| P1 | Tools → 原生 tool_calls 改造 | 后端编排协议升级（主线） | p1.0 ~ p1.6，7 步 | 无 |
| P2 | 消息点赞/点踩反馈闭环 | 全栈新功能 | p2.1 ~ p2.3，3 步 | 建议在 P4 之后做前端部分 |
| P3 | 侧边栏会话标题渐变蒙层 | 前端视觉小改 | p3.1，1 步 | 无 |
| P4 | 对话区居中布局（1200px） | 前端布局小改 | p4.1，1 步 | 无 |

**建议排期**：P1 为主线先行（协议开关可回退，风险最高、价值最大）；P3 / P4 为半天级纯前端小包，穿插在 P1 灰度观察期完成；P2 的后端部分（p2.1）可与 P1 并行，前端部分（p2.2）等 P4 布局定稿再动，避免消息区两次返工。

### 进度总览（随迭代更新）

| 步 | 内容 | 状态 | Tag |
| --- | --- | --- | --- |
| p1.0 | 能力表 + golden 用例冻结 | 已完成（2026-10-27） | `v2.0.0-p1.0` |
| p1.1 | Registry Schema 与 OpenAI tools 导出 | 已完成（2026-10-27） | `v2.0.0-p1.1` |
| p1.2 | llm.py 协议面（tools / tool_calls / 流式） | 已完成（2026-10-27） | `v2.0.0-p1.2` |
| p1.3 | brain 双协议 + 历史消息形态 | 已完成（2026-10-27） | `v2.0.0-p1.3` |
| p1.4 | react 执行环（多 call 串行 + 事件映射） | 已完成（2026-10-27） | `v2.0.0-p1.4` |
| p1.5 | 协议开关与灰度（react_protocol） | 已完成（2026-10-27，缺省 json） | `v2.0.0-p1.5` |
| p1.6 | 对照测试 + 文档收口 | 已完成（2026-10-27） | `v2.0.0-p1.6` |
| p2.1 | 反馈数据模型 + 接口（迁移 0013） | 已完成（2026-10-27） | `v2.0.0-p2.1` |
| p2.2 | 前端点赞/点踩 + 反馈弹窗 | 已完成（2026-10-27） | `v2.0.0-p2.2` |
| p2.3 | 管理端「意见反馈」页 | 待开工 | — |
| p3.1 | 侧边栏标题渐变蒙层 | 已完成（2026-10-27） | `v2.0.0-p3.1` |
| p4.1 | 对话区居中布局 1200px | 已完成（2026-10-27） | `v2.0.0-p4.1` |

---

## 3. P1 · Tools → 原生 tool_calls 改造（主线）

### 3.1 改造意图

**一句话**：继续自研 Registry / ReAct / NDJSON，只把「模型怎么声明与调用工具」从文本 ReAct JSON（thought/action/action_input，brain 统一拼协议提示词）换成 OpenAI 兼容的 `tools` / `tool_calls`；**不整包上 LangChain Tool 层**。

**要解决的问题**：坏 JSON、非法 action、缺参数 Schema、一步只能一个 action。
**要保留的**：现有 ToolResult、NDJSON 事件名、DAG 并行、Nest fail-closed 鉴权与业务错误分通道（配额/停止在图事件，鉴权 401/403 在网关，工具失败进 observation）。

### 3.2 范围与非目标

**范围内**：
- `llm.py` 请求/响应支持 `tools` 与 `tool_calls`（含流式增量累积）；
- `tools.py` / `agents.yaml` 注册处补 JSON Schema；
- `brain.py` / `react.py` 解析与执行原生 tool_calls；
- 历史消息改为 `assistant(tool_calls)` → `tool(tool_call_id)`；
- 协议开关灰度：`json | tool_calls | auto`；
- 按 `models.yaml` 做厂商能力探测（每模型 `supports_tools`）。

**明确不做**：不引入 LangChain `@tool`/ToolNode 替换 Agent 环；不重写 multi-agent DAG / orchestrator 并行模型；不动 Nest 鉴权与错误分通道；前端事件协议尽量零改动（复用 `tool_call_*` / `observation`）；不改 TokenPool / 配额语义。

### 3.3 现状对照

| 层 | 现状 | 改造后 |
| --- | --- | --- |
| 协议 | 文本 thought/action/action_input（`_PROTOCOL_TMPL` + `_render_history`） | API `tools` + `message.tool_calls` |
| LLM | 仅 messages / stream | + tools / tool_choice；读 tool_calls |
| Registry | name + description + parameters 文本示意 | JSON Schema + `describe_openai()` |
| 历史 | 观察拼进 user 文本 | `role: tool` + `tool_call_id` 回填 |
| 并行 | ReAct 串行；DAG 才并行 | 单轮可多 tool_calls（先串行执行）；DAG 不变 |
| 事件 | tool_call_start/end、observation | 语义保留，映射原生调用 |

### 3.4 目标架构

1. `Registry.describe_openai()` → OpenAI `tools[]`（`type: function` + name/description/parameters）。
2. `brain.next_step`：响应含 `tool_calls` → 返回结构化调用列表；无则终答 content。
3. `react.run_react`：按 id 执行每个 call → ToolMessage 回填 → 再调模型，直到无 tool_calls 或护栏触发（步数上限 / cancel 语义不变）。
4. `json` 模式保留为回退：模型不支持 tools 或开关关闭时走旧协议，行为与改造前完全一致。

### 3.5 分阶段任务

| 步 | 内容 | 交付物 | 测试 | Tag |
| --- | --- | --- | --- | --- |
| p1.0 | **基线与能力表**：盘点 `models.yaml` 12 对话模型对 tools / 并行 tool_calls / 流式 tool 增量的支持情况（逐模型点测）；准备 golden：合法单工具、一轮多工具、缺参、未知工具、纯终答、流式终答；冻结当前 NDJSON 事件契约 | 能力表（写进 `models.yaml` 注释或 `supports_tools` 字段）+ golden 用例清单 | — | `v2.0.0-p1.0` |
| p1.1 | **Schema 与 Registry**：`register(name, fn, description, parameters=None)`；缺 Schema 工具补最小 object schema 或标记 `schema_incomplete` 禁止进 tool_calls 白名单；新增 `describe_openai()`，旧 `describe()` 留给 json 模式 | `tools.py` | schema 导出/缺 Schema 拦截用例 | `v2.0.0-p1.1` |
| p1.2 | **llm.py 协议面**：`_chat_once` / `chat_stream` 增 `tools`、`tool_choice` 入参；非流式解析 `tool_calls`；流式累积 id/name/arguments 增量；参数校验失败给明确错误（勿静默丢弃） | `llm.py` | 解析/流式累积单测（mock 分片） | `v2.0.0-p1.2` |
| p1.3 | **brain + 历史**：tool_calls 路径不再「以 `{` 开头当 JSON」；维护 messages：system + user + `assistant(tool_calls)` + `tool` 消息；json 路径继续 `_PROTOCOL_TMPL` + `_render_history`；**同一轮禁止既拼 user 观察文本又发 tool 角色消息（双写禁忌）** | `brain.py` | 双协议分支 + 历史重建用例 | `v2.0.0-p1.3` |
| p1.4 | **react 执行环**：一轮多 tool_calls 先串行执行降风险；每个 call 发 `tool_call_start/end` + `observation`；`CAPABILITY_MISSING` / 执行异常写进 tool 结果文本；`tool_call_id` 执行与回填一一对应；保留步数上限与 cancel | `react.py`（`events.py` 尽量不改，必要时加可选 `tool_call_id` 字段，旧前端忽略未知字段） | 未知工具/坏 arguments/多 call 回填/取消与步数上限 | `v2.0.0-p1.4` |
| p1.5 | **开关与灰度**：配置 `react_protocol: json | tool_calls | auto`；`auto` = 模型支持且本轮工具皆有 Schema → tool_calls，否则 json；灰度顺序：单 Agent 内部 → 选模 → 全量单 Agent → multi 子 Agent 第二批 | `config.py` + `models.yaml`（`supports_tools`）+ `orchestrator` 传 protocol | auto 回退判定用例 | `v2.0.0-p1.5` |
| p1.6 | **对照测试与文档收口**：E2E 同一任务两种协议输出事件形状对照；灰度指标观测（任务成功率、平均步数、无效工具率、坏参数率、首 token/终答延迟、回退 json 比例）；更新 README 与本页验收勾选 | 迭代总结 + RELEASES | 全量回归三套测试 | `v2.0.0-p1.6` |

### 3.6 模块改动清单

| 模块 | 改什么 | 风险 |
| --- | --- | --- |
| `tools.py` | parameters Schema、OpenAI tools 导出、校验 | 中 |
| `agents.py` / `agents.yaml` | 注册处补 schema；工具白名单不变 | 低 |
| `llm.py` | tools 入参、tool_calls 出参、流式累积 | 高 |
| `brain.py` | 双协议分支；去掉纯文本 JSON 主路径依赖 | 高 |
| `react.py` | 多 call 执行、消息回填、事件映射 | 高 |
| `events.py` | 尽量不改；必要时加 `tool_call_id` 可选字段 | 低 |
| orchestrator / graph | 传入 protocol；multi 子图第二批 | 中 |
| config / models.yaml | `supports_tools`、默认 protocol | 低 |

### 3.7 升级注意事项（红线）

1. **厂商差异**：DeepSeek / SiliconFlow 对 tools、并行 tool_calls、流式 tool 增量支持不一致；上线前逐模型点测，不支持则 auto 回退 json，**禁止硬开**。
2. **Schema 完整性**：无 parameters 或 schema 过宽（一律 object 无 properties）会导致乱参；缺 Schema 的工具不进 `tools[]`。
3. **arguments 是 JSON 字符串**：必须 `json.loads`；流式截断要等结束再 parse；parse 失败回 `ToolResult.error`，勿抛崩整图。
4. **历史双写禁忌**：同一轮不要既拼 user 观察文本又发 tool 角色消息。
5. **tool_call_id**：执行与回填一一对应，丢 id 会被兼容 API 拒识。
6. **并行分层**：原生多 call 先串行执行；与 DAG 线程池并行是两层事，勿混配额/取消语义。
7. **流式**：终答 `content_delta` 与 tool_call 增量勿交错污染；multi 子任务脑 `stream=False` 可暂不接 tool 流式。
8. **安全**：tools 白名单仍以 `agents.yaml` 为准；模型点名未注册工具 → `CAPABILITY_MISSING`，禁止动态 import。
9. **错误通道**：工具失败不等于 HTTP 401；勿把 observation 错误塞进 Nest all-exceptions 总线。
10. **可观测性**：日志带 protocol、model、tool 名、call_id、是否回退，方便灰度对比。
11. **Prompt 债务**：切 tool_calls 后删除或收窄强迫输出 JSON 的 system 段，否则模型可能双重格式。

### 3.8 P1 验收标准

| # | 验收项 | 状态 |
| --- | --- | --- |
| 1 | 单工具任务：tool_calls 路径成功率不低于旧 json 路径（同模型同题） | 本地 E2E 对照通过；线上灰度实测待放量 |
| 2 | 一轮多 tool_calls：全部执行并正确回填后给出终答 | ✅ p1.6 E2E + golden |
| 3 | 未知工具 / 坏 arguments：观察含错误且任务不崩、可收敛或护栏停止 | ✅ p1.4 + p1.6 |
| 4 | 不支持 tools 的模型：auto 回退 json，行为与改造前一致 | ✅ p1.5 判定矩阵 |
| 5 | NDJSON：仍有 tool_call_start/end、observation、content_delta、done（前端零改动可跑） | ✅ p1.6 同形对照 |
| 6 | 取消与步数上限在两种协议下均生效 | ✅ p1.4 护栏按单元粒度复用 |
| 7 | 配额 paused / 鉴权 401 行为与改造前一致（未误接错误总线） | ✅ 错误通道未触碰，回归绿 |

### 3.9 P1 回滚

1. **配置回滚**：全局 `react_protocol=json`，无需撤代码即止血。
2. **代码回滚**：若 llm 流式解析有缺陷，回退至仅 json 分支的 release；Schema 注册保留无害。
3. **数据与前端**：无迁移数据；可选事件字段旧前端忽略即可。

---

## 4. P2 · 消息点赞/点踩反馈闭环

### 4.1 交互定义（状态机）

反馈主体 = **每轮对话的 assistant 消息**（消息气泡下方操作条，与复制/产物等既有操作并列）。

| 当前态 | 用户动作 | 结果 |
| --- | --- | --- |
| 无反馈 | 点赞 | 直接落库 `like`，点赞 icon 变实心 |
| like | 再点点赞 | 取消点赞，回退无反馈（DELETE） |
| like | 点点踩 | 打开点踩弹窗，提交后覆盖为 `dislike` |
| 无反馈 | 点点踩 | 打开点踩弹窗（见 4.2），提交后 `dislike` 生效 |
| dislike | 再点点踩 | **直接取消**点踩（不弹窗），回退无反馈 |
| dislike | 再点点踩前的任意时刻重新提交 | 二次点踩弹窗回显已选 tags/原因，提交后**覆盖当前反馈**，旧信息保留在流水表 |

- 激活态 icon 为**实心**（lucide `ThumbsUp`/`ThumbsDown`，激活时 `fill: currentColor`）；非激活为描边。
- 点赞无弹窗；点踩必须走弹窗（有原因才闭环）。
- 提交校验：至少选 1 个 tag，或「其他原因」有文字；二者满足其一即可提交。
- 取消（DELETE）只清当前态，流水表历史行不删。

### 4.2 点踩弹窗规格（对照参考截图定制）

| 项 | 规格 |
| --- | --- |
| 标题 | 抱歉话术：**「抱歉，这次回答没能帮到你」** |
| 副文案 | 「告诉我们哪里做得不好，我们会认真改进」（muted 小字） |
| 关闭 | 右上角 X；点击遮罩不关闭（防误触丢填写）；关闭=不提交 |
| 原因 tags（多选，chip 样式，选中高亮） | 适配本项目的口径：`误解了我的问题` / `上下文理解错误` / `回答模糊、不具体` / `数据或数字有误` / `图表或表格有误` / `工具调用有误` / `回答不专业` / `其他原因` |
| 其他原因 | 选中后展开多行输入框（textarea），placeholder「请描述具体的原因」，字数上限 200，右下角 `0/200` 计数 |
| 提交按钮 | 主色整宽按钮「提交反馈」；成功后关弹窗 + 轻提示（toast）+ 点踩 icon 转实心 |
| 视觉 | 沿用本项目深色主题（card/border/muted 变量），参考图仅取信息结构与流程 |

### 4.3 数据模型（迁移 `0013_message_feedback`）

**`message` 表加列（当前态，供消息列表快速渲染）**：

```sql
ALTER TABLE `message`
  ADD COLUMN `feedback`         VARCHAR(16)  NULL,  -- like / dislike / NULL
  ADD COLUMN `feedback_tags`    JSON         NULL,  -- ["数据或数字有误", ...]
  ADD COLUMN `feedback_comment` VARCHAR(200) NULL,  -- 其他原因文字
  ADD COLUMN `feedback_at`      DATETIME(6)  NULL;
```

**新表 `message_feedback`（append-only 流水，保留历史 + 管理端统计）**：

```sql
CREATE TABLE IF NOT EXISTS `message_feedback` (
  `id`         BIGINT       NOT NULL AUTO_INCREMENT,
  `message_id` BIGINT       NOT NULL,
  `session_id` VARCHAR(64)  NOT NULL,
  `user_id`    VARCHAR(64)  NOT NULL,
  `rating`     VARCHAR(16)  NOT NULL,              -- like / dislike
  `tags`       JSON         NULL,
  `comment`    VARCHAR(200) NULL,
  `created_at` DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`id`),
  KEY `idx_feedback_message` (`message_id`),
  KEY `idx_feedback_session` (`session_id`),
  KEY `idx_feedback_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- 写路径：每次提交/覆盖 = 插一行流水 + upsert `message` 当前态；取消 = 清 `message` 当前态、流水不删。这天然满足「之前点踩的信息保留、二次点踩覆盖当前」。
- **纪律**：迁移 0013 用原生 DDL；同步 `db/init.sql`；更新 `test_init_sql_columns_cover_required` 的 REQUIRED_COLUMNS 快照。

### 4.4 接口（网关透传）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/sessions/{session_id}/messages/{message_id}/feedback` | body `{rating, tags?, comment?}`；提交/覆盖（upsert） |
| DELETE | `/api/v1/sessions/{session_id}/messages/{message_id}/feedback` | 取消当前反馈（只清当前态） |
| GET | 随消息列表返回 | `message` 带出 `feedback` 四字段，前端直接渲染激活态 |

- 归属校验：message 必须属于该 session 且 session 属于当前用户，越权 **404 同形**（沿用 user_memory_repo 惯例）；只允许对 `role=assistant` 的消息反馈。
- 服务端校验：rating ∈ {like, dislike}；tags 必须在白名单枚举内（防脏数据）；comment ≤200；like 可不带 tags/comment，dislike 至少 1 tag 或 comment 非空。
- 网关：`routes.yaml` 增补透传（JWT 保护）；管理端接口走 admin 双闸。

### 4.5 管理端「意见反馈」页（p2.3）

- `/admin` 侧边菜单新增「意见反馈」：
  - 顶部统计卡：总反馈数、点赞数、点踩数、点踩率、Top 5 原因 tag；
  - 列表：时间倒序、分页；筛选 = rating / tag / 用户 / 时间段 / 关键词（comment）；行展开看完整 tags + comment + 跳转会话（复用任务监控的定位模式）。
  - 只读，不提供删除/修改（审计一致性）。

### 4.6 P2 验收标准

| # | 验收项 |
| --- | --- |
| 1 | 点赞/取消点赞即时生效，刷新后状态保持（DB 为真相源） |
| 2 | 点踩弹窗：tag 多选、「其他原因」展开输入框、0/200 计数、抱歉话术文案 |
| 3 | 二次点踩覆盖当前反馈且旧信息在流水表可查；直接再点实心点踩 = 取消 |
| 4 | 越权（他人消息）反馈返回 404 同形；assistant 消息以外不可反馈 |
| 5 | 管理端可按 rating/tag/用户/时间筛选并看到统计 |
| 6 | pytest（repo+归属+校验+流水追加）、vitest（弹窗交互/状态机）、jest（网关透传）全绿 |

---

## 5. P3 · 侧边栏会话标题渐变蒙层

### 5.1 现状与方案

- 现状：`AppSidebar.tsx` 的 `SessionTitle` 已做 overflow 检测（`scrollWidth > clientWidth`），悬停态有 marquee 跑马灯；截断是硬边。
- 方案：`.session-title` 加右缘渐变蒙层——溢出时右侧 ~24~28px 由不透明渐变到透明，被截断的文字「若隐若现」（参考截图效果）：

```css
.session-title.is-overflow {
  mask-image: linear-gradient(to right, #000 calc(100% - 26px), transparent);
  -webkit-mask-image: linear-gradient(to right, #000 calc(100% - 26px), transparent);
}
```

- `is-overflow` 由既有 overflow 检测驱动；**marquee 滚动进行中移除蒙层**（滚动时文字完整可视，停止后恢复），避免蒙层吃掉滚动中的文字。
- 深色主题下 mask 与背景色无关（alpha 蒙层），无需配色适配。

### 5.2 验收

1. 长标题右侧有渐隐效果，能看到被截断文字的「边缘」；
2. 短标题（无溢出）无蒙层；
3. 悬停跑马灯滚动期间文字不被蒙层遮挡；
4. vitest：overflow 类切换逻辑用例。

---

## 6. P4 · 对话区居中布局（1200px）

### 6.1 现状与方案

- 现状：`chat-main` 下 `message-scroll`（padding 20/24）与 `composer-wrap` 全宽拉伸，宽屏下消息行过长；`prompt-bar` 组件自带 `--pb-w`（工作台已放开为 100%）。
- 方案：引入统一内容列容器，**宽度 `min(1200px, 100%)`、水平居中**——≥1200px 时两侧留白对称，<1200px 时整屏铺满并按空间自然收缩：

```css
.chat-column {
  width: min(1200px, 100%);
  margin-inline: auto;
}
```

- 应用点：`message-scroll` 内部包一层 `.chat-column`（消息列表、welcome 区）、`composer-wrap` 内部包 `.chat-column`（prompt-bar）、`chat-header` 内容同样对齐到该列——三者共享同一列宽，视觉上竖向对齐成一条中轴。
- `welcome` 居中样式不受影响；`ChartView` 等宽组件（width=1200）在列内自适应 `max-width: 100%`。
- 不引入新断点逻辑，纯 `min()` 表达式即可完成「够宽留白、不够宽铺满」。

### 6.2 验收

1. 宽屏（≥1200px 内容区）：消息列、输入条、标题三者左缘/右缘对齐，整体居中；
2. 窄屏（<1200px）：整屏铺满无横向滚动，间距按现有 padding 收缩；
3. 图表/表格/文件卡片在列内不溢出；
4. 手动验证文档（宽屏 1440 / 窄屏 1024 / 800 三档截图核对）。

---

## 7. 风险与回滚总表

| 工作包 | 主要风险 | 缓解 | 回滚 |
| --- | --- | --- | --- |
| P1 | 流式 tool_calls 解析缺陷；厂商支持差异；历史双写 | auto 回退 + 逐模型点测 + 红线清单 §3.7 | `react_protocol=json` 配置止血 |
| P2 | 迁移漂移致生产 500；越权反馈 | 列级护栏 + init.sql 同步 + 404 同形归属校验 | 0013 downgrade；功能开关（可选 env `FEEDBACK_ENABLED`，fail-closed 缺省 off→灰度开） |
| P3 | 蒙层遮挡滚动文字 | marquee 期间移除蒙层 | 纯 CSS/类名，直接还原 |
| P4 | 既有全宽组件（图表/表格）在列内溢出 | max-width:100% + 三档宽度手动验证 | 纯样式，直接还原 |

## 8. 里程碑建议

1. **M1（第 1 周）**：p1.0 ~ p1.2（能力表 + Schema + llm 协议面）；穿插 p3.1、p4.1 两个半天级小包。
2. **M2（第 2 周）**：p1.3 ~ p1.5（brain/react/灰度）；p2.1 后端接口并行推进。
3. **M3（第 3 周）**：p1.6 对照收口；p2.2 / p2.3 前端与管理端；全量回归 + RELEASES，打 `v2.0.0` 收官 tag（CI 自动部署上线）。

---

## 附录 A · 《Tools → 原生 tool_calls 改造文档》要点摘录（P1 素材来源）

- **决策**：自己封装 + 原生 tool_calls + 协议开关；LangChain Tool 层不在范围。错误层继续「统一错误码、分通道处理」。
- **建议配置键**：`react_protocol: json | tool_calls | auto`；`models.yaml` 每模型 `supports_tools`。
- **灰度顺序**：单 Agent 内部 → 选模 → 全量单 Agent → multi 子 Agent；前端优先零改动。
- **灰度指标**：任务成功率、平均步数、无效工具率、坏参数率、首 token/终答延迟、回退 json 比例。
- **回滚三级**：配置回滚（protocol=json）→ 代码回退（仅 json 分支 release）→ 数据/前端（无迁移、可选字段向后兼容）。
- **验收 7 条**见 §3.8（原文档全部勾选为「待测」，实现推进后回填）。
