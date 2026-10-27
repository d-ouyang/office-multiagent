# 灰度观察 · tool_calls vs json 用例清单（验收 1 配套）

> 目的：PLAN-2.0.0 §3.8 验收第 1 条——「单工具任务：tool_calls 路径成功率不低于旧 json 路径（同模型同题）」，并顺带采集灰度指标（平均步数 / 无效工具率 / 坏参数率 / 延迟）。
> 现状：生产已切 `REACT_PROTOCOL=tool_calls`（2026-10-27），真任务冒烟已过（deepseek-chat，单工具 + 终答链路完整）。
> 用法：按 §3 双轮对照跑一遍清单，填 §5 记录表，对照 §6 判定线出结论，回填 PLAN 验收表。

---

## 1. 成功与失败的判定标准（先定义，再统计）

一条任务记 **成功**，须同时满足：

| # | 条件 | 数据来源 |
| --- | --- | --- |
| 1 | `done` 事件 status ∈ {done, single, multi}（非 error/paused） | NDJSON / `task.status` |
| 2 | 终答里的关键数字与工具观察对得上（validator 未报 `result_validator` 不一致，或人工抽查一致） | trace / 人工 |
| 3 | 未触发崩溃性护栏：无 `error` 事件；重复调用护栏触发但**收敛给出结论**算成功（半分场景见 §6） | NDJSON |
| 4 | 步数 ≤ max_iterations（10） | `agent_run.iterations` |

记 **失败**：任务 error 结束 / 终答数字与观察矛盾 / 反复幻觉工具名被强制收尾 / 用户可见的"模型输出无法解析"。

## 2. 指标定义与 SQL 口径（生产库直接查）

| 指标 | 口径 | SQL（按时间窗 `:start`/`:end` 换） |
| --- | --- | --- |
| 任务成功率 | done 类 / 全部 | `SELECT status, COUNT(*) FROM task WHERE created_at >= :start GROUP BY status` |
| 平均步数 | `AVG(iterations)` | `SELECT AVG(iterations) FROM agent_run ar JOIN task t ON t.id=ar.task_id WHERE t.created_at >= :start` |
| 无效工具率 | CAPABILITY_MISSING / 无效名 / 参数解析失败占比 | `SELECT tool, error, COUNT(*) FROM tool_call_log WHERE error IS NOT NULL AND error != '' GROUP BY tool, error`（配合 trace 里 `工具参数解析失败`） |
| 坏参数率 | `工具参数解析失败` observation 次数 / 工具调用总次数 | 查 `tool_call_log` + trace，或 NDJSON 里 `tool_call_end success=false` 计数 |
| tokens/任务 | `AVG(task.tokens_used)` | `SELECT AVG(tokens_used) FROM task WHERE status LIKE '%done%' AND created_at >= :start` |
| 延迟 | 任务创建→结束（trace done.ts - status ts，或人工掐表） | NDJSON 首/尾事件 ts 差 |

> tool_call_log 的 error 列在 json 时代就有；两轮用同一 SQL 即可比。

## 3. 双轮对照执行方法

同一批问题、同一模型，两种协议各跑一轮，顺序无所谓（推荐先 json 后 tool_calls，避免"越跑越熟"的心理偏差——其实模型无状态，主要是防手滑记录串轮）：

```bash
# 轮 A：json 基线
ssh 服务器 → /opt/office/.env 改 REACT_PROTOCOL=json → docker compose -f docker-compose.prod.yml up -d office-backend
逐题执行（记录表 §5 左半）
# 轮 B：tool_calls（当前生产态，如果先跑 B 再跑 A 也行）
.env 改回 tool_calls → up -d office-backend
逐题执行（记录表 §5 右半）
```

- **模型**：全清单用 `deepseek-chat`（主力）；再用例 U2 / U6 两题换 `glm-5.3-flash-sf` 各复测一遍（跨厂商抽查）。
- **账号**：统一用演示账号 `dev`（消耗其钱包额度，不污染真实用户数据）。
- **每题独立新会话**，避免上下文互相影响。
- 每题执行后立即在 §5 表里记：结果（✅/⚠️/❌）、步数（事件数/观察条数）、tokens、终答数字对不对、体感延迟。

## 4. 用例清单（12 条，覆盖六类协议路径 + 真实业务）

### A 组 · 单工具直查（对应 golden `single_tool`）

| ID | 提问 | 预期（两种协议都应达到） | 重点观察 |
| --- | --- | --- | --- |
| U1 | 10月卖得最好的前5个城市是哪些？ | 调 query_orders(group_by=city, metric=sum_pay) 一次，终答给 5 城市名单，数字与观察一致 | 已冒烟通过；记基线数字 |
| U2 | 2026年9月的订单总数是多少？ | 调 query_orders(date 范围 9 月) 一次，终答含总数；**换 glm-5.3 复测** | 简单题步数应=1 |
| U3 | 查一下订单号 GW20261001001 的订单详情 | 单工具精确查询；订单不存在时**如实说没有**（0 行不是编数据） | 参数命名是否照 Schema |

### B 组 · 多工具串联 / 一轮多 call（对应 golden `multiple_tools`）

| ID | 提问 | 预期 | 重点观察 |
| --- | --- | --- | --- |
| U4 | 9月和10月各卖了多少，哪个月高？ | query_orders 两次（或 compare_orders）→ 终答对比结论；tool_calls 轮可能出现一轮两个 call（tool_id 不同且都执行） | 多 call 串行执行、id 一一对应 |
| U5 | 画一张10月各城市销售额的柱状图 | query_orders(group_by=city) → render_chart，**出现 visual 事件**且图能渲染 | 链式调用；clean_id 传递 |
| U6 | 10月各渠道订单占比，画饼图 | 同上，pie；**换 glm-5.3 复测** | 跨厂商多工具 |

### C 组 · 参数密集（坏参数率高发区）

| ID | 提问 | 预期 | 重点观察 |
| --- | --- | --- | --- |
| U7 | 除退款外，10月上海和北京的订单总额分别是多少？ | city 列表 / exclude_status 参数正确；两个城市数字分开 | 复杂 filters/数组参数是否照 Schema 传 |
| U8 | 最近三个月每个月的退款金额趋势 | group_by=month + exclude_status 或 order_status=已退款；月份对齐 | 日期推导（"最近三个月"） |
| U9 | 帮我导出10月全国订单明细 Excel，要包含门店和支付金额 | export_orders；fields 含存在列；「支付方式」这类不存在的列应整列省略并在返回里说明，**不编列** | 枚举/数组/字段映射 |

### D 组 · 未知工具 / 能力缺失（对应 golden `unknown_tool`）

| ID | 提问 | 预期 | 重点观察 |
| --- | --- | --- | --- |
| U10 | 帮我把这张照片修成古风滤镜 | image_restore 无工具实现 → 观察含 CAPABILITY_MISSING → 终答**如实说暂不支持**，不编造、不崩 | 任务不崩可收敛；步数不空转 |
| U11 | 帮我发一封邮件给张伟 | 无邮件工具 → 如实说明 + 建议替代（如生成邮件文稿 write_document） | tool_calls 轮是否幻觉出不存在的工具名 |

### E 组 · 纯对话 / 流式终答（对应 golden `final_only` / `stream_final`）

| ID | 提问 | 预期 | 重点观察 |
| --- | --- | --- | --- |
| U12 | 你能帮我做什么？简单介绍一下 | **零工具调用**，直接打字机流式终答 | tool_calls 轮终答流式是否正常；无多余工具调用 |

### F 组 · 文档链路（read_document 多轮）

| ID | 提问 | 预期 | 重点观察 |
| --- | --- | --- | --- |
| U13 | 读一下我上传的《XX 制度.pdf》，总结要点 | read_document（需先上传文件）→ 摘要来自文档，引用原文不编造 | 跨轮次 tool 消息历史回填正确性（多轮 ReAct） |

> U13 需要先在 dev 账号传一个文件；两轮用**同一个文件**。

## 5. 记录表模板（复制去填）

| ID | json 轮：结果/步数/tokens/数字对/延迟 | tool_calls 轮：结果/步数/tokens/数字对/延迟 | 差异备注 |
| --- | --- | --- | --- |
| U1 | | | |
| U2 | | | |
| … | | | |

汇总行（跑完填）：成功率 A/B、平均步数 A/B、失败清单。

## 6. 判定线（对照 PLAN 验收 1 + 灰度指标预期）

| 指标 | 预期 | 判定 |
| --- | --- | --- |
| **任务成功率** | tool_calls ≥ json 轮（同题逐条看，不要求逐题全等） | tool_calls 轮失败题多于 json 轮 → 记录差异题，复盘后重跑一次确认 |
| 平均步数 | tool_calls ≤ json（一轮多 call 可合并步数）或相当（±1 步） | 明显变多 → 查是否幻觉重试 |
| 无效工具率 / 坏参数率 | tool_calls ≤ json（Schema 约束应更准） | 坏参数率 > 5% → 查对应工具 Schema |
| tokens/任务 | 相当（±15%） | 明显变大 → 查 tool 消息历史是否双写 |
| 体感延迟 | 相当（首 token < 3s 量级不变） | 明显变慢 → 查流式分片处理 |
| 幻觉工具名 | 两种协议都不应出现"none/null"类无效名 | tool_calls 轮如出现未注册名 → 走 CAPABILITY_MISSING 收敛，记入观察 |
| 已知限制 | 流式 tool_calls：正文片段先于 tool_calls 到达时，先推片段归为思考 | 灰度期人工留意 UI 上"答非所问前缀"，出现即记录（p1.6 已知限制） |

**回滚触发线**（任一命中即 `.env` 改回 json + `up -d office-backend`，并把现象发我）：
1. tool_calls 轮成功率比 json 轮低 ≥10 个百分点；
2. 出现连续 2 次以上的"模型输出无法解析"或协议级畸形（缺 id/name）；
3. 真实用户反馈回答明显变差且能复现到 tool_calls 行为差异。

**结论回填**：跑完把 §5 表贴回给我（或让任务跑着，我来汇总），我在 `PLAN-2.0.0.md` §3.8 验收 1 勾选，并把这批数字记进迭代文档。
