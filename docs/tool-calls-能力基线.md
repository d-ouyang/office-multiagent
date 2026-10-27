# 原生 tool_calls 能力基线（v2.0.0-p1.0）

> 点测时间：2026-10-27。方式：通过线上 `office-backend` 已有密钥做只读云端请求；不重启服务、不改配置、不写业务数据。每模型最多非流式/流式各一次，`max_tokens=256`。
> 点测脚本：`backend/scripts/probe_tool_calls.py`。统一使用 `get_weather(city)` 最小 Schema，要求模型必须调用工具；校验 call id、函数名及 arguments 可解析为 JSON object。

## 结果

| 模型 | 非流式 tool_calls | 流式增量 tool_calls | 非流式耗时 | 流式耗时 |
| --- | --- | --- | --- | --- |
| deepseek-chat | 通过（HTTP 200） | 通过（HTTP 200） | 944ms | 829ms |
| deepseek-reasoner | 通过 | 通过 | 583ms | 866ms |
| deepseek-v3-sf | 通过 | 通过 | 1612ms | 1982ms |
| deepseek-r1-sf | 通过 | 通过 | 4411ms | 4792ms |
| deepseek-v4.1-flash-sf | 通过 | 通过 | 1066ms | 877ms |
| deepseek-v4-flash-sf | 通过 | 通过 | 1447ms | 1987ms |
| glm-5.3-flash-sf | 通过 | 通过 | 1491ms | 1298ms |
| longcat-2.0-sf | 通过 | 通过 | 2127ms | 1845ms |
| hy4-preview-sf | 通过 | 通过 | 16916ms | 1461ms |
| deepseek-v4-pro-sf | 通过 | 通过 | 4412ms | 3444ms |

结论：当前 10 个对话模型的 `supports_tools` 均可置 `true`。这里只证明基础单工具与流式增量能力；并行 tool_calls 的模型行为仍在 p1.4 golden/E2E 验证，auto 灰度不因此跳过。

## Golden 与事件契约

`backend/tests/golden/tool_calls_cases.json` 冻结六类用例：合法单工具、一轮多工具、缺参、未知工具、纯终答、流式终答。`test_tool_calls_baseline.py` 校验用例完整性、call id / JSON arguments，以及事件名仍属于既有 NDJSON 契约。

前端依赖的 `content_delta / tool_call_start / tool_call_end / observation / done` 不变；本步未改 `events.py`，未引入新事件字段。
