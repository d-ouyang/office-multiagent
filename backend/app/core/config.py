"""后端配置：从环境变量 / .env 读取（pydantic-settings）。

compose 里各服务用服务名做主机名（mysql / redis / chroma），
本地直跑时改 .env 指向 localhost 即可。
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "office-multiagent"

    mysql_host: str = "mysql"
    mysql_port: int = 3306
    mysql_user: str = "office"
    mysql_password: str = "office_pass"
    mysql_database: str = "office"

    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0

    chroma_host: str = "chroma"
    chroma_port: int = 8000
    # chroma 不可用时是否致命：false=健康态降级，不阻断启动（设计文档 §12.3 共享 Chroma）
    require_chroma: bool = False

    # ---- 日志（设计文档 §十八）----
    log_level: str = "INFO"          # DEBUG / INFO / WARNING / ERROR
    log_format: str = "json"         # json（生产/远端采集）/ text（本地调试）

    # ---- 鉴权（设计文档 §13.3；参考 RAG internal-auth.client.ts）----
    # 用户 JWT 的共享密钥（网关 passport-jwt 签、后端 PyJWT 验，二者共用）
    jwt_secret: str = ""
    # 服务间内部调用共享密钥（网关↔后端走 X-Internal-Token，hmac 比对，fail-closed）
    internal_shared_secret: str = ""

    # ---- 模型注册表（配置驱动，非硬编码；§十七）----
    models_config: str = ""          # 留空则自动定位 backend/config/models.yaml

    # ---- 规划器（配置驱动，§四.2/§四.3）----
    planner_config: str = ""         # 留空则自动定位 backend/config/planner.yaml
    decision_model: str = "decision-llm"
    intent_ambiguity_low: float = 2.0
    intent_ambiguity_high: float = 4.0

    # ---- 业务 Agent 注册表（p5.1b，配置驱动 §五）----
    agents_config: str = ""          # 留空则自动定位 backend/config/agents.yaml

    # ---- Skill 能力层（P1，配置驱动：docs/项目架构调整-引入Skill层-2026-10-24.md）----
    # 能力包目录；留空则自动定位 backend/app/skills。
    # P1 仅加载不接路由，是否启用由每个 skill 自己的 spec.yaml 的 enabled 决定。
    skills_dir: str = ""

    # ---- 云端模型密钥（仅存环境变量，不进 git）----
    siliconflow_api_key: str = ""
    deepseek_api_key: str = ""

    # ---- Phase 5 · 办公能力池（p5.1a）----
    # Brain 用的对话大模型 id（config/models.yaml 注册表里的 id）
    llm_brain_model: str = "deepseek-chat"
    llm_timeout: float = 120.0
    # v2.0.0-p5.1：LLM 重试参数配置化（此前 range(3) 与 0.8*(attempt+1) 硬编码在
    # core/llm.py 两条路径里）。llm_max_retries=额外重试次数，总尝试 = 1 + 该值，
    # 缺省 2 与 p6.7b 现状一致；0 表示完全关闭重试。
    llm_max_retries: int = 2
    llm_retry_backoff: float = 0.8        # 网络/5xx 退避基数：sleep = 基数 × (attempt+1)
    llm_retry_backoff_429: float = 2.0    # 限流退避基数：429 需要等更久，与网络抖动不同量级
    # v2.2.0-p1.4（B1）：LLM 网关收口开关。非空时【全部】模型调用的 base_url 重写为
    # 该地址、api_key 重写为 INTERNAL_SHARED_SECRET（服务间密钥）——models.yaml 保持
    # 直连定义不变（测试稳定），切流量/回退都是改这一个环境变量 + restart backend。
    # 容器网络地址（如 http://gateway:3000/llm/v1）；留空 = 直连（B1 之前的现状）。
    llm_gateway_url: str = ""
    # v2.2.0-p1.5（B2）：prompt cache 命中部分的计价折扣（0~1）。缺省 0.25 对齐
    # DeepSeek hit/miss 价比（¥0.5/M vs ¥2/M 量级）；1.0 = 全价（B2 之前行为）。
    # 生效点：TokenPool.settle 的 billed 计算，钱包按折扣价扣费、ledger 记 billed。
    llm_cache_price_ratio: float = 0.25
    # v2.0.0-p5.3：工具级重试退避基数。此前 ToolRegistry.call 缺省 backoff=0.0，
    # 重试是「立即再打一次」，对 DB/网络瞬时抖动几乎无效。只改间隔、不改重试次数，
    # 因此不引入新的副作用风险（非幂等工具的重试次数与现状完全一致）。
    tool_retry_backoff: float = 0.3
    # v2.0.0-p5.4：checkpointer 后端。memory=缺省，保持现状（每次调用独立 MemorySaver，
    # 进程重启即丢，续跑走 routes 的重跑式）；sqlite=进程级共享 + 落盘，跨重启可恢复，
    # 且 resume 时不重跑已完成的节点（探针实测：memory 新实例会静默从头重跑）。
    checkpointer_backend: str = "memory"
    checkpoint_sqlite_path: str = "data/checkpoints.sqlite"
    # v2.0.0-p1.5：ReAct 协议开关灰度。json=文本协议（现状）；tool_calls=OpenAI 原生
    # function calling（模型不支持时自动回落 json 并告警，禁止硬开）；auto=按模型
    # supports_tools + 本轮工具 Schema 完整性自动选。缺省 json=fail-closed。
    react_protocol: str = "json"
    # RAG 检索工具（外部工具：走 RAG 后端内部接口，带网关证明；rag p4.11 认 office 域密钥）
    rag_base_url: str = "http://127.0.0.1:8000"
    rag_internal_secret: str = ""       # 须与 RAG 后端 OFFICE_GATEWAY_SHARED_SECRET 同值
    rag_service_username: str = "office-service"  # 注入 X-Username（须能在 RAG user 表解析）
    # export_orders 明细导出的单次行数上限（p6.30）
    export_orders_max_rows: int = 5000
    # db_query 工具护栏：强制 LIMIT 行数上限
    db_query_max_rows: int = 50
    # read_document 工具：文档目录（工具只能读该目录内文件，防路径穿越）与单次返回字符上限。
    # p6.9：8000 → 50000——"通读整篇"场景 2 万字文档一次拿全（1M 上下文模型/128K 模型都装得下）
    documents_dir: str = "data/upload"
    doc_read_max_chars: int = 50000
    # token 池（§十四）：/tasks 默认预扣估算（LLM 用量事前估不准，用门槛值兜底；
    # settle 时按真实 usage 补差）
    token_estimate_default: int = 2000
    # 单任务全局硬上限：与钱包余额无关，对所有用户生效。0 表示关闭。
    task_token_hard_limit: int = 50000
    # DAG 层内最大并行子任务数（p4.3c；防 LLM 渠道限流，1=串行回落基线）
    dag_max_concurrency: int = 3

    # ---- 轻量结果校验器（p6.29，P1 拍板：数字对账 observation，不阻断）----
    result_validation: bool = True

    # ---- 显式长期记忆（p6.29，P1 拍板：user_memory 表，用户可查可删）----
    user_memory_max_items: int = 100     # 每用户上限；满了如实拒绝（不静默淘汰）
    user_memory_content_chars: int = 300  # 单条内容长度上限
    user_memory_inject_limit: int = 20   # 每轮注入提示词的最大条数
    user_memory_inject_chars: int = 4000  # 注入块总字符上限（背景四段 + 短条目）
    user_profile_section_chars: int = 2000  # 背景里每一段的字数上限

    # ---- 连接层加固（p1.2a）----
    mysql_pool_size: int = 5
    mysql_max_overflow: int = 10
    mysql_pool_timeout: int = 30
    redis_socket_timeout: float = 2.0
    redis_socket_connect_timeout: float = 2.0
    redis_health_check_interval: int = 30
    chroma_timeout: float = 5.0
    # 启动探活重试：compose 起停顺序下，DB/Redis 可能晚于 backend 就绪
    connect_max_retries: int = 3
    connect_retry_backoff: float = 1.0


settings = Settings()
