# PLAN-2.2.0 · Harness 工程化

> 立项：2026-11-11，分支 `feature/2.2.0-harness`（自 feature/2.1.0-hitl 切出）。
> 依据：`~/Desktop/AIAgent/迭代计划-harness工程化-office2.2.0-rag4.1.0.md`（路线全文）+ 《agent-harness 两个项目差异盘点》。
> 纪律不变：每步 testcase + tag `v2.2.0-pN.M`（老 tag 永不重打）+ 迭代文档 + RELEASES 更新 + 推送。
> 硬约束：COST-007 / Redis 仅缓存与队列 / 单机 4C4G（不上 Temporal、K8s、Langfuse 全家桶）。
> **顺序铁律：先抽契约再收口，先收口再分布式。**

## Phase A 契约层（p1.x）— M1：换实现不改调用点

- [x] **A1 ModelAdapter 契约**（p1.0，2026-11-11）：`core/model_adapter.py`（Protocol + OpenAICompatAdapter + FakeModelAdapter + set/get/reset）；llm.chat/chat_stream 变门面转发。判据达成：Fake 注入跑通 run_react 全链路，调用点零改动。pytest 497。
- [x] **A2 ToolSpec 契约**（p1.1，2026-11-12）：`ToolSpec` 落在真实注册表 `orchestration/tools.py`（非 skills 层，运行时零引用）；13 工具集中批注表（agents.py `_TOOL_SPECS`）；非幂等副作用重试 WARNING。判据达成：unannotated()==[] + 白名单裁剪不丢 spec。pytest 507。
- [x] **A3 Event 契约 v1**（p1.2，2026-11-12）：`core/events.py` Event 补 trace_id/tenant_id/payload（8/8 字段）；emitter 构造注入；run_trace 透明兼容。判据达成：pytest 513 + **vitest 123 全绿**，老 NDJSON 行解析向后兼容。
- [x] **A4 Policy / StateSnapshot / EvalCase**（p1.3，2026-11-12）：`core/contracts.py` 集中三契约（frozen dataclass + Protocol，零运行时副作用）；StateSnapshot.version 对齐事件流 seq（恢复语义基石）。判据达成：10 条单测 0.01s（零库依赖），pytest 523。**Phase A 完结——六契约全落地。**

## Phase B 模型收口与预算（p2.x）— M2：绕过网关的调用在 CI 被拦截

- [x] **B1 LLM 网关收口**（p1.4，2026-11-13）：**方案修正**——服务器 swap 打满放弃 LiteLLM 容器，改为 gateway 内置 LLM 代理路由（+~30MB，零新容器）；backend 侧 `llm_gateway_url` env 开关（models.yaml 不动，秒级回退）；冒烟 5/5 + 全链路真任务验证 + CI 收口检查已挂部署流。⚠️ 尚未部署生产（等用户确认）。详见 docs/iterations/v2.2.0-p1.4-llm-gateway.md。
- [ ] B2 归因元数据（tenant/user/feature/run/step/env）入口注入全程透传；记账改 provider 回报 usage；prompt cache 折扣价。
- [ ] B3 三级硬预算（预扣+429 短路+软告警）；max_steps+状态指纹循环护栏做成网关级开关。融合：RAG 侧 OFFICE_GATEWAY_SHARED_SECRET、钱包 settle 下限保护。

## Phase C 执行保障（p3.x）— M3：kill -9 无重复副作用

- [x] **C1 幂等键**（p1.7，2026-11-14）：tool_invocation 表 UNIQUE(run_id,tool_name,args_hash)（迁移 0014+init.sql 同步）；react 加 invocation_guard（lookup 命中复用观察 / record 登记），三层防线（重复提示→硬拦→幂等缓存）。判据达成：同 run 重投副作用恰好 1 次。pytest 543。⚠️ 未部署（含迁移 0014，代码对表缺失已降级）。
- [ ] C2 run_id lease（MySQL GET_LOCK）+ 分级超时 + 重试计入预算 + 死信。
- [ ] C3 durable 加固（sync checkpointer + 副作用幂等包装 + step 级进度落库收窄重跑范围）。融合：0001 迁移多语句修复。

## Phase D 事件流与上下文（p4.x）— M4：run_id 全轨迹回放

- [ ] D1 四套日志合一 append-only 事件流（S2 契约）；audit 作投影；GET /runs/{id}/replay。
- [ ] D2 融合：记忆语义检索（Chroma）；模型池扩逻辑模型（LiteLLM 路由）。

## Phase E 评测闭环（p5.x）— M5：改 Prompt 未过门禁不能灰度

- [ ] E1 golden set（灰度用例+validator+点踩反馈自动回流）+ CI 回归门禁。
- [ ] E2 融合：validator 误报复核、is_ambiguous 放宽（可选）。
- [ ] E3 融合：write_document xlsx/pdf、视觉 OCR、自反思（可选）、演示 KB 补销售口径制度。

## Phase F 前端与账号（穿插，不阻塞主线）

- [ ] F1 bundle 代码分割 · F2 FeedbackTab tsc 清零 · F3 /admin 登录页同步
- [ ] F4 logout 服务端吊销策略（评估 token_version vs 短 TTL）
- [ ] F5 账号收尾（外部依赖）：boss 体验期结束后执行生产 dev 密码轮换 SQL（已备好）+ test 账号处置

## 已知外部依赖 / 冻结项

- 生产 dev 密码轮换：**冻结**（boss 体验期，dev/Office@2026 对外有效中；SQL 已备）。
- 上一版本遗留观察：HITL p1.7~p1.13b 已随 v2.1.0-p1.13c 上线（2026-11-11），待真任务验收。
