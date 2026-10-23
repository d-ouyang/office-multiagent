# p4.3 实施计划 · DAG 结果传递与层内并行

**日期**：2026-10-23 ｜ **状态**：待开工 ｜ **预计 tag**：`v1.0.0-p4.3`
**一句话**：让 multi 路由的 DAG 调度真正做到「有依赖的子任务接上一步的结果，没有依赖的放在同一层一起跑」。

---

## 1. 任务来源与规划位置（在哪里）

| 规划出处 | 原文/内容 |
| --- | --- |
| 设计文档 §四.3《路由与执行》（`智能办公助手-多Agent系统设计方案-总结.md` 第 66 行） | 「复杂 → Orchestrator 按 DAG 调度，**支持串行/并行后汇总**」 |
| `docs/PLAN-1.0.0.md` Phase 4 / v1.0.0-p4.1（第 89 行） | orchestrator.py「DAG 拓扑分层 + run_dag 调度汇总」——**基线层内串行** |
| `backend/app/orchestration/orchestrator.py` 第 1-3 行（p4.1 原文遗留注释） | 「基线层内串行（确定性、可测），**并行化（asyncio.gather）留作后续**，接口已按"层"组织好」 |
| 《架构对比与实施建议》（2026-10-23）P2 项 | DAG 层内并行：接口已留，改 asyncio.gather 约 0.5 天；触发条件=多子任务慢的真实投诉 |

## 2. 现状缺口（2026-10-23 实读代码核实）

| # | 缺口 | 证据 | 影响 |
| --- | --- | --- | --- |
| 1 | **上游结果没有传给下游** | `graph.py:115` `run_react(f"{st.intent} 任务", ...)`——子任务文本只有 intent，DAG 的依赖边只决定执行顺序，上游产出对下游不可见 | 「先清洗再分析」形同虚设：分析 Agent 拿不到清洗结果，只能自己重新调工具或编造 |
| 2 | **层内串行** | `orchestrator.py` `run_dag` 中 `for st in level:` 顺序执行 | 无依赖子任务（如 rag + cleaning）本可并行，却串行烧时间 |
| 3 | **multi 路由 token 不落账** | `graph.py:194-198` multi_node 只返回 `{"result": ...}`，未返回 `tokens_used` → `graph.py:310` settle 时 `actual=0`，预扣全额退回 | 多 Agent 任务的真实消耗不计入账本（§十四 对账恒等式破洞） |

## 3. 任务清单（按依赖顺序）

| # | 任务 | 改动文件 | 验收标准（testcase） |
| --- | --- | --- | --- |
| 1 | `run_dag` 把已完成的上游 `results` 透传给 `agent_runner`（签名扩展，保持默认参数向后兼容） | `orchestration/orchestrator.py` | 单测：DAG `A→B`，runner 收到 B 时能拿到 A 的 `AgentResult`；无依赖子任务收到空上游 |
| 2 | `spec_agent_runner` 拼子任务文本：`intent + 上游结果摘要`（各上游 final，截断上限沿用 observation 摘要纪律；上游 `hit_cap` 时如实标注「上游未完成」，不伪装成结果） | `orchestration/graph.py` | 单测：B 的任务文本包含 A 的关键数字；上游失败时文本含失败标注且不含伪造数据 |
| 3 | 层内并行：`asyncio.gather` + `run_in_executor`（ReAct 是同步函数，**不能裸 gather**） | `orchestration/orchestrator.py` | 单测：同层 3 个 sleep 桩子任务总耗时 ≈ max 而非 sum；层间依赖顺序不被并行破坏 |
| 4 | 并发事件安全：仍走主 emitter，验证 seq 严格递增无重复（p4.1 教训：子 emitter seq 独立会乱序） | `core/events.py`（如需要加锁）+ 测试 | 单测：并发 3 子任务推事件，收集后 seq 严格递增、无重复 |
| 5 | token 汇总：multi_node 返回 `tokens_used` = 各子任务 `brain.usage.total_tokens` 之和 | `orchestration/graph.py` | 单测：settle 的 actual 等于各子任务用量之和；StubBrain 基线为 0 时全额退回不变 |
| 6 | 并行度配置化：`DAG_MAX_CONCURRENCY`（默认 3，防 LLM 渠道限流；0/1=串行可回落） | `core/config.py` + `docker-compose.yml` 注入 | 配置生效；设为 1 时行为与现在完全一致（回落开关） |
| 7 | 回归 + tag + 总结文档（项目纪律） | — | pytest/jest/vitest 全绿（不低于当前基线数）；tag `v1.0.0-p4.3`；`docs/iterations/v1.0.0-p4.3-*.md` 总结 |

## 4. 风险与纪律（执行时必守）

- **ReAct 同步 → 并行必须走线程池**：`LlmBrain.next_step` 内是同步 `chat`/`chat_stream`，`asyncio.gather` 直接包同步函数不会并行；用 `loop.run_in_executor` 或 `asyncio.to_thread`。
- **LLM 渠道限流**：硅基流动/DeepSeek 对并发有限制，默认并发 3，配置化可调；超出的子任务排队而非硬发。
- **事件流纪律**：并发下仍只用主 emitter（`graph.py:114` 已有注释），子任务的 status/observation 事件必须带 `subtask_id` 才能归位。
- **摘要化纪律不变**：上游结果进下游任务文本也要走截断/摘要，别把 2 万字 Observation 原样塞进去（p6.7/p6.9 教训）。
- **确定性**：测试环境 StubBrain 不加随机延迟，并行测试用 sleep 桩断言时序。

## 5. 不在本次范围

- LLM 分解增强（DecisionModel 插槽，规则覆盖不足时再启用）。
- 前端 multi 子任务并行态可视化（子任务并行时的进度展示，可留待后续 p6.x）。
- DAG 失败重试/部分失败策略（本次只做「如实传递失败」）。

## 6. 完成后更新

- `docs/PLAN-1.0.0.md`：Phase 4 增加 p4.3 完成记录 + 进度总览表。
- `docs/RELEASES.md` + `docs/iterations/v1.0.0-p4.3-*.md`（五件套：迭代文档/RELEASES/CHANGELOG/.env PROJECT_VERSION/PLAN 标状态）。
- 工作区记忆日志。
