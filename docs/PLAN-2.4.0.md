# PLAN-2.4.0 · 结构与工具层根治（意图 requires + 文档分段 + 失败文案）

> 立项：2026-11-17，分支 `feature/2.4.0-routing-and-io`（自 `feature/2.3.0-context-budget` 切出）。
> 依据：2026-11-16/17 两次真链路冒烟暴露的两处**结构债**——它们不是参数问题，改配置修不掉：
>   ① 意图到工具靠人工维护的 `capability_guards` 映射（漏了"文件"，导致文件在却读不了）；
>   ② `read_document` 只能整读或截尾，超过单步上限就丢掉文档末尾（第 10 章看不到）。
> 纪律不变：每步 testcase + tag `v2.4.0-pN.M` + 迭代文档 + RELEASES 更新 + 推送。
> 相对 2.3.0 的定位：2.3.0 解决"上下文被打爆"，2.4.0 解决"路由选错人 / 工具读不全"。
>
> **进度（2026-11-17）**：A/B/C 三步代码完成，pytest 615 passed / 3 skipped，真链路验证通过；未打 tag。
> 实施中修正了两处判据（见文末"实施记录"）：A 的"删光 guards"不可达（requires 是意图级、
> guards 是实体级，互补而非替代）；另外发现并修掉"单步上限 = 任务上限"的死锁（p2.1）。

---

## 0. 两处结构债（为什么必须改结构，不能只调参数）

### 0.1 意图 → 工具是手写映射

现状（`config/planner.yaml:72-99`）：

```yaml
capability_guards:
  订单: query_orders
  制度: rag_retrieve
  图表: render_chart
  读取文件: read_document     # v2.3.0-p1.3 才补上
```

预检逻辑（`core/router.py:53-70`）：文本含某实体词 且 主 Agent 工具池缺该工具 → 改道 general。

**问题**：这张表是人肉维护的"说法 → 工具"字典。每加一个工具、每多一种说法（"读取/打开/查看/这份"）
就要同步一次，**注定漏**——2026-11-16 漏的就是"文件"，表现为"文件在目录里，模型却说没有工具"。
历史同类补丁已有三次（p5.5 删弱词、p5.6 加预检、p6.33 校准标签），都是往这张表上贴。

### 0.2 读文档只能整读

现状（`orchestration/tools_doc.py:298-317`）：`content[:max_chars]`，`max_chars` 上限 50000。

**问题**：文档超过单步上限（v2.3.0-p1.4 调到 50000）就只能截尾。模型看不到末尾章节，
只能"按规律推断"——虽然如实标注了推断（这是对的），但用户要的是数字，不是推断。
真正的解法是**分段读**：先看结构，再定位章节。

---

## 1. Phase A：意图的能力声明（p1.x）

### A1 `intents.requires` 字段（配置）

```yaml
intents:
  rag:
    keywords: [...]
    agent: rag_retrieval
    requires: [rag_retrieve]        # 这个意图的 Agent 必须拥有这些工具
  analysis:
    agent: data_analysis
    requires: []                    # 纯分析不需要额外工具
```

**动哪里**：`config/planner.yaml`（7 个意图各加 requires）、`core/planner.py::Plan` 增加 `requires` 聚合字段。

**判据**：`plan("读取文件 a.md")` 的 Plan 带上 `requires=["read_document"]`。

### A2 预检改按 requires 判定（代码）

`router._capability_reroute` 从"遍历实体词表"改为：

```python
required = set().union(*(cfg["intents"][i].get("requires", []) for i in plan.intents))
missing = required - pools.get(primary_agent, set())
if missing:
    return "general"
```

**关键设计**：requires 由**意图**声明，不是由**说法**声明。新增工具时只需在意图里写一次，
不需要枚举用户可能怎么说。文件读取天然落在 general（它是唯一拥有 read_document 的 Agent）。

**动哪里**：`core/router.py:53-70`、`core/planner.py`。

**判据**：**从 planner.yaml 删掉全部 11 条文件类 guards 后**，「读取文件 smoke.md」仍改道 general。
这一条是 A 系列的验收核心——它证明"不再依赖实体词枚举"。

### A3 兼容与清理

- `capability_guards` 保留一个版本作为"实体级补充"（如"订单 → query_orders"这种**跨意图**的强实体约束，
  requires 表达不了），在文档里标注为 deprecated 的兜底，不再往里加新词。
- `single_agent_covers` 不动（它回答的是"一个 Agent 能否顺序完成多意图"，与 requires 正交）。

### 测试（tests/test_intent_requires.py，6 条）

| 编号 | 用例 | 断言 |
| ---- | ---- | ---- |
| A-1 | 计划对象带 requires | `plan("查报销制度").requires == ["rag_retrieve"]` |
| A-2 | 文件读取意图声明 | `plan("读取文件 a.md")` 的 requires 含 `read_document` |
| A-3 | 缺工具改道 | rag Agent 缺 read_document → general |
| A-4 | **删掉 guards 后仍生效** | 临时清空 `capability_guards`，A-3 结论不变 |
| A-5 | 不误伤 | 「生成周报文档」仍归 report_generation |
| A-6 | 覆盖多意图 | rag+analysis 双意图时取 requires 并集 |

---

## 2. Phase B：read_document 分段（p2.x）

### B1 工具签名

```python
read_document(file_name, offset: int = 0, limit: int = 0) -> {
    "file_name", "total_chars", "offset", "returned_chars",
    "content", "has_more": bool, "next_offset": int | None,
}
```

- `limit=0` → 沿用 `doc_read_max_chars`（老行为，不破坏现有调用）；
- 越界 offset → 如实报错（不返回空串让模型猜）；
- `has_more/next_offset` 让模型知道"还有下一段"，而不是自己算。

### B2 提示词与章节感知

- general / analysis Agent 的 system_prompt 加一条：文档超过 3 万字先读 `offset=0, limit=5000`
  看结构，再按章节定位；`has_more=true` 时不要声称"已读全文"。
- 可选增强：`read_document` 返回 `headings`（前 20 个 Markdown 标题 + 偏移），让模型一次就能定位。
  **先不做**，等 B1 真跑数据说话（避免过早加复杂度）。

### 测试（tests/test_doc_paging.py，5 条）

| 编号 | 用例 | 断言 |
| ---- | ---- | ---- |
| B-1 | 默认不分段 | 不传 offset/limit 时返回全文（与旧行为逐字一致） |
| B-2 | 分段拼接完整 | 两次读（0/5000 + 5000/5000）拼起来等于全文前 10000 字 |
| B-3 | has_more 正确 | 5 万字文档读前 5000 → `has_more=true` 且 `next_offset=5000` |
| B-4 | 越界 offset | 报错文案含"超出文档长度"，不返回空串 |
| B-5 | 真跑回归 | 2.4 万字的 `smoke-long2.md` 分两段读完，能答出第 10 章数字 |

### 判据

同一份 5 万字文档：B1 之前只能答前半（截尾）；B1 之后分两段读完，能答出末章数字，
且单次返回不超过 `doc_read_max_chars`。

---

## 3. Phase C：失败文案区分"能力缺失 / 信息缺失"（p3.x）

现状：文件在目录里，模型说"我没有读取工具，请上传文件"——用户无法分辨是系统没能力、
还是自己没传文件。

### C1 前置检查（代码）

`ask_user` 触发前（或 read_document 失败时），先查目录：

```python
if check_inside_base(base, name).is_file():
    return "文件在文档目录里，但当前任务没有读取权限，已为你改道重试"
else:
    return "没有找到这个文件，请上传或告知确切文件名"
```

**动哪里**：`orchestration/tools_doc.py`（read_document 的 FileNotFoundError 分支）、
`orchestration/tools_ask.py`（ask_user 的文件类问句）。

### 测试（tests/test_doc_missing.py，3 条）

| 编号 | 用例 | 断言 |
| ---- | ---- | ---- |
| C-1 | 文件存在但无权 | 文案含"文件在"，不含"请上传" |
| C-2 | 文件确实不存在 | 文案含"没有找到/请上传" |
| C-3 | 路径越界 | 仍按护栏报错，不泄漏目录结构 |

---

## 4. 顺序与工作量

**A → B → C**。理由：A 影响面最大（路由），先做能立刻收敛"文件读不了"；B 独立可并行；
C 依赖 A/B 的文案（改道后才有"已为你改道"这句话）。

| Phase | 内容 | 量级 |
| ----- | ---- | ---- |
| A | requires 字段 + 预检改写 + 6 testcase | 1 天 |
| B | 分段读取 + 5 testcase + 提示词 | 1 天 |
| C | 文案分流 + 3 testcase | 半天 |

**测试基线**：594 → A 600 → B 605 → C 608。

---

## 5. 不做

- **不做意图的向量/LLM 全量分类**：规则 + 小模型两层已经够用，全量分类会让每次任务多一次模型调用
  （成本 + 延迟），收益不明。
- **不做"全 Agent 共享全量工具"**：白名单的价值是"最小权限 + 提示词聚焦"，不能为了方便放弃。
- **不改 `single_agent_covers`**：它回答的是"一个 Agent 能否顺序完成"，与工具能力正交。
- **不给 read_document 加摘要能力**（让模型自己总结正文）：那是 C 层的事，2.3.0 已做。

---

## 6. 实施记录（2026-11-17）

### A 阶段：intents.requires（7 testcase）

- `planner.yaml`：7 个意图各加 `requires`（analysis: [] / orders: [query_orders] / cleaning: [clean_table] /
  report: [write_document] / rag: [rag_retrieve] / visualization: [render_chart] / image_restore: []）。
- `planner.Plan` 新增 `requires` 字段，`plan()` 在**折叠可视化之后**聚合（避免已剔除意图带入依赖）。
- `router._capability_reroute` 改为接收 Plan，需求 = `plan.requires ∪ guards 命中项`，
  返回 `(目标, 缺失工具)`，reason 里写明缺什么（可观测）。
- **判据修正**：原计划写"删掉 11 条文件类 guards 后仍能改道"——**做不到也不该做**。
  requires 是"意图级"（这个意图需要哪些能力），guards 是"实体级"（这句话里出现了什么）。
  "读取文件"不是意图，是任务形态，requires 表达不了。两者互补，实测也无法互替。
  改为两条真判据：
  - **A-4 配置自洽护栏**：遍历所有意图，断言 `requires ⊆ 该意图 Agent 的工具池`（CI 门槛，防配置漂移）；
  - **A-5 工具池被改坏时改道**：monkeypatch 把 `query_orders` 从 data_analysis 挪走 → 订单任务自动改道 general。

### B 阶段：read_document 分段（7 testcase）

- 签名 `read_document(file_name, offset=0, limit=0)`，返回增 `offset / returned_chars / has_more / next_offset`。
- `limit` 受 `doc_read_max_chars` 二次约束（模型传 999999 也只给 5 万）；
  越界 offset 直接报错不返回空串；`truncated` 保留为 `has_more` 的兼容别名。
- 工具描述与 schema 同步（offset 说明"续读用 next_offset"，并警告"has_more=true 时不得声称读完全文"）。

### C 阶段：文件名自我纠正（3 testcase）

- 原计划是"区分能力缺失/信息缺失"，但实现中发现 p1.3 的路由修正已经消掉了"没有工具"那一类；
  剩下的真实痛点是**文件名写错**（`smoke_md` vs `smoke-long.md`）被当成"文件不存在"→ 反问用户。
- 改为：`FileNotFoundError` 里附 `difflib` 相似文件名候选（≤3 个），并明确"请直接重试，不要向用户索要
  这些已经存在的文件"。指向性更强，且不改变任何权限语义（路径护栏仍在 ValueError 分支）。

### p2.1 附带修复：单步上限与任务上限的死锁

真链路第一次验证直接 `paused_budget`，只有 1 次工具调用：

- 单步上限（p1.4 调到 50000）**等于**任务上限（`TASK_TOKEN_HARD_LIMIT=50000`）——
  读一份 5 万字文档，第一次调用就把任务预算打满。
- 修：`task_token_hard_limit` 默认 50000 → **200000**；`docker-compose.yml` 与 `.env.example` 同步。
  加护栏 `test_task_budget_covers_multiple_doc_reads`（断言 ≥ `doc_read_max_chars × 2`）。
- 部署注意：生产 `.env` 若固定了 `TASK_TOKEN_HARD_LIMIT=50000`，会覆盖新默认，需同步改。

### 真链路（本地，9.3 万字 `big-doc.md` / 20 章）

| 轮次 | 改动前 | 改动后 |
| ---- | ------ | ------ |
| 读第 20 章 | 只能到前 10 章（截尾） | **2 次 read_document**（第二次带 offset）→ 答「100000 元」并引用原文 |
| 任务状态 | `paused_budget`（1 次调用就撞上限） | `single`，tokens 162,069 |

测试基线：**598 → 615 passed / 3 skipped**。
