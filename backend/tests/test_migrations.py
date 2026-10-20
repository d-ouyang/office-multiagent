"""迁移基线测试（p1.2c）。

护栏（可反向验证）：基线迁移必须与 db/init.sql 建同一批表，防止两份 schema 漂移；
env.py 必须用 core.config 的 DATABASE_URL 覆盖占位 URL（单一真相源）。
不连库、不跑迁移（点5：DB 操作谨慎，这里只做静态/导入校验）。
"""
import importlib.util
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]      # office-multiagent/backend
MIG_DIR = BACKEND / "migrations"
INIT_SQL = BACKEND.parent / "db" / "init.sql"
MIG_FILE = MIG_DIR / "versions" / "0001_initial_baseline.py"


_TABLE_RE = re.compile(
    r"CREATE TABLE IF NOT EXISTS `(\w+)`"      # init.sql / 基线 execute 风格
    r"|create_table\(\s*[\"'](\w+)[\"']"        # alembic op.create_table 风格
)


def _table_names(sql_text: str) -> set[str]:
    return {m.group(1) or m.group(2) for m in _TABLE_RE.finditer(sql_text)}


def test_baseline_matches_init_sql_tables():
    init_tables = _table_names(INIT_SQL.read_text(encoding="utf-8"))
    # 漂移护栏升级（p6.2c）：init.sql 必须与【全部 migrations】（0001 基线 + 后续迁移）表集合一致
    mig_tables: set[str] = set()
    for mig in sorted((MIG_DIR / "versions").glob("*.py")):
        mig_tables |= _table_names(mig.read_text(encoding="utf-8"))
    assert init_tables, "init.sql 没解析到表"
    assert init_tables == mig_tables, (
        f"迁移与 init.sql 表不一致：多 {mig_tables - init_tables}，"
        f"少 {init_tables - mig_tables}"
    )
    assert len(init_tables) >= 12


def test_baseline_seeds_present():
    text = MIG_FILE.read_text(encoding="utf-8")
    # 种子幂等（INSERT IGNORE），且含模型池/用户
    assert "INSERT IGNORE INTO `model_pool`" in text
    assert "INSERT IGNORE INTO `pool_model`" in text
    assert "INSERT IGNORE INTO `user`" in text


def test_baseline_module_importable_and_revision():
    spec = importlib.util.spec_from_file_location("m0001_initial", MIG_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # 需 alembic / sqlalchemy 已装
    assert mod.revision == "0001_initial"
    assert mod.down_revision is None
    assert callable(mod.upgrade) and callable(mod.downgrade)


def test_env_wired_to_config_url():
    env = (MIG_DIR / "env.py").read_text(encoding="utf-8")
    assert "from app.core.db import DATABASE_URL" in env
    assert 'set_main_option("sqlalchemy.url", DATABASE_URL)' in env


def test_script_template_exists():
    assert (MIG_DIR / "script.py.mako").exists()
    assert (BACKEND / "alembic.ini").exists()
