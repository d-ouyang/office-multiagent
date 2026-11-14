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


# --------------------------------------------------------------------------- #
# 列级漂移护栏（p6.43）：p1.2c 只比表名，message.trace 曾因列漂移导致生产 500
# （历史查询 SELECT ... trace ... 报 1054）。REQUIRED_COLUMNS 是「线上真实 schema」
# 的列清单快照；init.sql 缺任何一列即失败。
# 纪律：迁移加了列 → 同步 init.sql → 同步更新本清单。
# --------------------------------------------------------------------------- #
REQUIRED_COLUMNS: dict[str, set[str]] = {
    "agent_run": {"id", "subtask_id", "iterations", "token_used", "duration_ms"},
    "asset": {"id", "task_id", "user_id", "type", "name", "rel_path", "storage_url", "created_at"},
    "audit_log": {"id", "actor_user_id", "actor_username", "actor_role", "action", "target_type",
                  "target_id", "target_label", "detail", "ip", "created_at"},
    "message": {"id", "session_id", "role", "content", "trace",
                "feedback", "feedback_tags", "feedback_comment", "feedback_at", "created_at"},
    "message_feedback": {"id", "message_id", "session_id", "user_id", "rating",
                         "tags", "comment", "created_at"},
    "model_pool": {"id", "name"},
    "pool_model": {"pool_id", "model_name", "enabled"},
    "runtime_setting": {"setting_key", "setting_value", "updated_at"},
    "session": {"id", "user_id", "model", "title", "pinned", "pinned_at", "created_at"},
    "subtask": {"id", "task_id", "agent_type", "depends_on", "result_json", "status"},
    "task": {"id", "session_id", "complexity", "status", "text", "result", "tokens_used",
             "pause_reason", "pause_payload", "retry_of", "request_json", "created_at"},
    "task_source": {"id", "task_id", "type", "ref", "title", "url"},
    "token_ledger": {"id", "user_id", "task_id", "agent_run_id", "model", "input_tokens",
                     "output_tokens", "cache_read", "reserve", "settle", "kind", "note",
                     "amount", "created_at"},
    "tool_call_log": {"id", "agent_run_id", "tool", "params", "error", "success"},
    "user": {"id", "employee_id", "username", "password_hash", "role", "model_pool_id",
             "token_version", "created_at"},
    "user_memory": {"id", "user_id", "section", "content", "source", "created_at"},
    "wallet": {"user_id", "balance"},
}


def _init_sql_columns() -> dict[str, set[str]]:
    """从 init.sql 解析每张表的列名（CREATE TABLE 块内以反引号开头的行）。"""
    sql = INIT_SQL.read_text(encoding="utf-8")
    cols: dict[str, set[str]] = {}
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS `(\w+)` \((.*?)\) ENGINE=InnoDB", sql, re.S):
        table, body = m.group(1), m.group(2)
        names = {c.group(1) for c in re.finditer(r"^\s*`(\w+)`", body, re.M)}
        cols[table] = names
    return cols


def test_init_sql_columns_cover_required():
    cols = _init_sql_columns()
    for table, required in REQUIRED_COLUMNS.items():
        missing = required - cols.get(table, set())
        assert not missing, f"init.sql 的 `{table}` 缺列（迁移已加、init.sql 没同步）：{sorted(missing)}"


def test_0001_single_statement_per_execute():
    """C3（v2.2.0-p1.9）：0001 的每个 op.execute 必须是单条语句——MySQL 单次
    execute 不允许多语句，此前的大块导致纯 alembic 全新装必炸（已拆分修复）。"""
    src = (MIG_DIR / "versions" / "0001_initial_baseline.py").read_text(encoding="utf-8")
    blocks = re.findall(r'op\.execute\(\s*"""(.*?)"""', src, re.S)
    assert blocks, "0001 应包含 op.execute 语句"
    for i, b in enumerate(blocks):
        body = b.strip().rstrip(";")
        assert ";" not in body, (
            f"0001 第 {i} 个 op.execute 含多条语句（分号分隔）——纯 alembic 全新装会炸，必须逐语句拆分：{body[:80]}..."
        )
