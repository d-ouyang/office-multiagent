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


settings = Settings()
