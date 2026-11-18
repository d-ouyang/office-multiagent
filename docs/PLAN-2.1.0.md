
---

## 附录 D：工具层健壮性计划（2026-11-10 立项）

> 背景：生产实测模型猜字段名（m_sum_pay vs metric_value）浪费轮次；选 md 生成 pdf（格式漂移）。
> 参考标准：OpenAI function calling strict mode / Anthropic tool use best practices（职责与边界写入描述）/ MCP 工具注解。

### D1 工具描述质量系统化审计（13 个工具过一遍）
- 每个工具描述五要素：职责（做什么）/ 边界（不做什么）/ 输入约束（枚举>自由文本，带反例）/ 返回结构（自描述）/ 常见错误（报错含义与下一步）。
- 新增工具 PR 按此标准走（checklist 进 PR 模板可选）。

### D2 消费前校验（工具间数据契约）
- clean 表消费（render_chart/analyze_table/write_document）：调用前校验 y/列名是否在表实际列中，**报错带"实际列+推荐列"**（已部分有），进一步：列不存在时自动映射（指标中文名/别名表反查）。
- 产物索引带 columns（已做 p1.10），消费侧 schema 校验补齐。

### D3 字段名猜错计数
- react 循环内对「同类工具+同类错误」（列不存在/参数校验失败）计数：第 1 次错 → 正常回观察；第 2 次错 → 观察追加强提示（含合法值清单+上次错误复述）；第 3 次错 → 硬停止该路径，模型必须换策略或 ask_user。

### D4 用户偏好硬约束（prefs 贯穿）
- ask_user questions 支持 key（schema 已加 p1.10）；resume 时收集 key→answer 存任务 prefs；
- write_document/render_chart 执行时：prefs 有 format/指标选择 → **后端强制覆盖模型传参**（观察注明"已按用户选择执行"）——当前靠提示词软约束（p1.10 已强化），prefs 贯穿是硬约束落地。

### D5 strict mode 试点
- 硅基流动对 tool_calls schema 的 strict 支持度验证；支持则对枚举型参数（chart/agg/format）开启。
