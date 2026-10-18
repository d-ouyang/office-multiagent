"""Alembic env：用 core.config 的 DATABASE_URL（与 compose 服务名 / .env 一致）。

URL 不写死在 alembic.ini，而是在这里用 set_main_option 覆盖，确保本地 / 容器 /
远端都用同一份配置来源（单一真相源）。本项目基线为原生 DDL 迁移（镜像 db/init.sql），
暂不使用 autogenerate，故 target_metadata = None。

运行（在 backend/ 目录）：
    alembic upgrade head      # 建表 / 升级
    alembic downgrade -1      # 回退一步
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.db import DATABASE_URL

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 覆盖占位 URL 为配置来源的 URL（compose 服务名 / .env / 环境变量一致）
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# 基线用原生 DDL，不用 ORM metadata 自动生成
target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
