# 项目亮点 · ReAct 决策协议改造：JSON 文本协议 → OpenAI 原生 tool_calls

> 面试向文档。对应 2.0.0 P1（p1.0~p1.6）+ 灰度实测；量化数据来自生产环境双轮对照（见 `docs/灰度观察-对照结果-2026-10-27.md`）。
> 一句话版本：**把"让 LLM 按提示词格式吐 JSON 再用正则解析"的决策协议，换成 OpenAI 原生 function calling，生产实测任务成功率 81%→100%、协议级幻觉 10 次→0 次，glm 模型单任务成本降低 7 倍。**

---

## 1. 背景：多 Agent 办公助手的决策链路

整体链路（骨架改造前后不变）：

```
浏览器 → NestJS 网关(JWT/配额) → FastAPI + LangGraph
       → Planner(规则意图) → Router/Decomposer(单Agent / 多Agent DAG)
       → ReAct 循环(run_react) → 工具池(13 个真实工具)
       → NDJSON 事件流(SSE) → 前端(打字机 + 步骤面板)
```

ReAct 循环是核心：`Brain 决策 → 调工具 → 观察回填 → 再决策 → … → 终答`。改造前后的差异**全部集中在这一段**。

## 2. 改造前：JSON 文本协议的三个结构性缺陷

旧协议靠 system 提示词强迫 LLM 每步输出固定格式 JSON：

```
A. 需要调工具：{"thought": "...", "action": "工具名", "action_input": {...}}
B. 任务完成：直接写自然语言终答
```

真跑暴露的问题：

| 缺陷 | 表现 | 后果 |
| --- | --- | --- |
| **幻觉动作** | LLM 输出 `"action": "none"` 或编造工具名 | 需要专门的 invalid_action 兜底；连续 2 次幻觉被迫"护栏强制收尾"，用户直接看到机器话 |
| **解析脆弱** | `{` 开头但 JSON 截断/带前后缀 → 双协议分支（流式还得"等完整再判断是不是 JSON"） | 解析失败只能如实停止；流式打字机与决策步互相牵制 |
| **历史靠文本拼接** | 工具结果摘要拼进 user 消息文本，上一轮"思考"也是文本 | 上下文卫生差（曾撑爆导致幻觉），多轮多工具时模型容易重复调用 |

另外每轮只能表达**一个**动作，模型天然被迫多轮往返。

## 3. 改造后：双协议架构（可配置、fail-closed）

三层各改一段，其余链路零改动：

```
                    ┌─ json 路径（保留，缺省）：提示词模板 + extract_json 解析
LlmBrain(决策脑) ───┤
                    └─ tool_calls 路径（新增）：
                         请求:  tools = ToolRegistry.describe_openai()  (13 工具 JSON Schema)
                                history = assistant(tool_calls) → tool(tool_call_id) 原生消息对
                         响应:  message.tool_calls → ToolCall{id, name, arguments, parse_error}

run_react(执行环) ── 新增"动作单元"：Step.calls 一轮多 call 串行展开，逐个
                     执行/去重/发事件；tool_id 使用厂商原生 call id

llm.py(协议面) ───── chat/chat_stream 支持 tools/tool_choice；流式按 index
                     增量累积 tool_calls，流结束统一回调（正文/思考/工具三分通道）
```

**工具调用具体流程（tool_calls 路径，一步的完整生命周期）：**

1. **注册期**：13 个工具在注册处声明参数 JSON Schema（与函数 kwargs 一一核对，`additionalProperties=false`），护栏测试保证"无 Schema 不导出"；
2. **请求期**：brain 组装 `tools[]`（缺省 `tool_choice="auto"`）+ 原生历史（assistant 的 tool_calls 与 tool 角色的观察一一配对，**绝不**把观察拼进 user 文本）；
3. **响应期**：`message.tool_calls` 解析为 `ToolCall`；arguments 解析失败**不抛异常**，落 `parse_error` 由执行环回填为工具错误观察（红线：坏参数不炸整图）；
4. **执行期**：每个 call 独立走 去重护栏 → 工具执行 → `tool_call_start`（tool_id=原生 call id）→ `observation` → `tool_call_end` 事件序列；文件产物/图表/外部 token 结算逻辑复用；
5. **回填期**：每个 call 一条历史 Step，供 brain 重建 `assistant(tool_calls) → tool` 消息对，模型天然看到"我调了什么、拿到了什么"。

**NDJSON 事件流对前端零改动**：`tool_call_start/end、observation、content_delta、done` 同形（E2E 对照测试锁死），前端从不知道协议换了。

## 4. 协议机制对比

| 维度 | json 文本协议 | 原生 tool_calls |
| --- | --- | --- |
| 工具认知 | 提示词里列清单，靠模型"自觉照格式" | `tools[]` 结构化传入，模型原生理解 |
| 动作表达 | 每轮 1 个 JSON 对象 | 一轮可返回多个 tool_calls |
| 参数约束 | 无（模型自由发挥，错参靠工具兜底） | JSON Schema 强约束（枚举/数组/嵌套对象） |
| 结果回填 | 摘要拼进 user 文本 | `tool` 角色 + `tool_call_id` 精确配对 |
| 幻觉动作 | `"action":"none"` / 编造名，需兜底 | 协议层不存在（未注册名走 CAPABILITY_MISSING 观察通道） |
| 流式打字机 | "先判断是不是 JSON"双分支 | 正文/思考/工具增量三分通道，终答真流式 |
| 切换能力 | — | `react_protocol: json\|tool_calls\|auto`，不支持模型/Schema 不齐自动回落 |

## 5. 量化结果（生产环境双轮同题实测，deepseek-chat 为主 + glm 抽查）

16 用例（单工具/多工具/参数密集/能力缺失/纯对话/文档链路），各跑 json 轮与 tool_calls 轮：

| 指标 | json | tool_calls | 变化 |
| --- | --- | --- | --- |
| **任务成功率** | 13/16 = **81%** | 16/16 = **100%** | +19pp |
| 无效工具名幻觉 | 10 次 | **0 次** | 根除 |
| 护栏强制收尾（用户看到机器话） | 2 次 | **0 次** | 根除 |
| 平均步数 | 1.8 | 1.2 | -33% |
| 平均耗时（deepseek 口径） | 4.4s | 6.0s | 相当（±噪声） |
| **glm 极端案例**（多工具画图） | 145,699 tokens / **34 分钟** | 19,947 tokens / 23 秒 | **tokens -86%，耗时 -98.9%** |
| 工具路由错误（订单号拿去查知识库） | 1 次 | 0 次 | 根除 |

失败模式对比：json 轮 2 个硬失败是"连续幻觉工具名 → 强制收尾"，用户终答直接是 *"模型连续给出无效工具名，已强制停止"*——这在 tool_calls 路径下协议层不可能发生。

## 6. 工程纪律（面试追问的弹药）

- **能力不猜，点测说话**：10 个对话模型逐个真实调云端验证 tools/流式 tool_calls（`supports_tools` 三态登记），文档宣传≠实际兼容。
- **fail-closed 开关**：显式 `tool_calls` 但模型未点测或 Schema 不齐 → 自动回落 json + warning（禁止硬开）；缺省 json，上线行为零变化。
- **同形事件对照测试**：同一任务双协议跑 `run_react`，断言 `tool_call_start/end、observation、content_delta` 关键字段完全一致——"前端零改动"不是口号是测试。
- **坏参数不炸图**：`parse_error` 随结构下传，执行环回填为工具错误观察（与"LLM 输出畸形抛崩整图"是两类错误、两种处理）。
- **灰度可逆**：切协议 = 改一个环境变量 + 容器重建，30 秒回滚。

## 7. 面试话术

**30 秒版**：
"我们的多 Agent 办公助手用 LangGraph 编排 ReAct 循环，最初决策协议是提示词强迫 LLM 输出 JSON 再正则解析，生产上频繁出现幻觉动作名、需要护栏兜底。2.0 我做了原生 function calling 改造：三层拆分——llm 层管协议面（流式增量累积 tool_calls）、brain 层管双协议与原生历史回填、react 层管多 call 串行执行环；配了 fail-closed 开关和双协议同形事件的 E2E 对照。生产双轮实测：成功率 81%→100%，协议级幻觉从 10 次降到 0，glm 模型最差案例成本降了 86%，而前端 NDJSON 事件流零改动。"

**预埋追问**：
- *为什么不用 LangChain 自带 agents？* —— 我们要 NDJSON 事件流同形、护栏（去重/无效名/token 结算）在执行环统一收口，自研执行环才能保证两协议行为可对照。
- *多 call 为什么串行不并行？* —— 先降风险：配额/取消/护栏语义都在单元粒度；并行收益等灰度数据，且与 DAG 层并行是两层事。
- *parse_error 为什么不抛？* —— 坏参数是业务态不是系统态：回填工具错误让模型自纠，抛了会浪费整轮；协议畸形（缺 id/name）才抛。
- *怎么保证没回归？* —— 缺省 json + 存量 400+ 测试零断言改动 + 双协议同形 E2E + 灰度回滚演练（实际切了 4 次）。
