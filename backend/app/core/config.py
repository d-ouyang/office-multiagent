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

    # ---- 云端模型密钥（仅存环境变量，不进 git）----
    siliconflow_api_key: str = ""
    deepseek_api_key: str = ""


settings = Settings()
