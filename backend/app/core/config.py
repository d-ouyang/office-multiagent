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

    # ---- 业务 Agent 注册表（p5.1b，配置驱动 §五）----
    agents_config: str = ""          # 留空则自动定位 backend/config/agents.yaml

    # ---- 云端模型密钥（仅存环境变量，不进 git）----
    siliconflow_api_key: str = ""
    deepseek_api_key: str = ""

    # ---- Phase 5 · 办公能力池（p5.1a）----
    # Brain 用的对话大模型 id（config/models.yaml 注册表里的 id）
    llm_brain_model: str = "deepseek-chat"
    llm_timeout: float = 120.0
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
    # DAG 层内最大并行子任务数（p4.3c；防 LLM 渠道限流，1=串行回落基线）
    dag_max_concurrency: int = 3

    # ---- 轻量结果校验器（p6.29，P1 拍板：数字对账 observation，不阻断）----
    result_validation: bool = True

    # ---- 显式长期记忆（p6.29，P1 拍板：user_memory 表，用户可查可删）----
    user_memory_max_items: int = 100     # 每用户上限；满了如实拒绝（不静默淘汰）
    user_memory_content_chars: int = 300  # 单条内容长度上限
    user_memory_inject_limit: int = 20   # 每轮注入提示词的最大条数
    user_memory_inject_chars: int = 1500  # 注入块总字符上限（上下文卫生）

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
