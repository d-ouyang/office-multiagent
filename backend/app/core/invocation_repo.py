"""幂等键贯穿（v2.2.0-p1.7 / Phase C1）——tool_invocation 去重表。

为什么要有：断点续跑/重试/重投是 C 阶段的常态（kill -9、lease 抢占、死信重放），
副作用类工具（写文件/发请求/落库）绝不能因重跑而重复执行。幂等键 =
(run_id, tool_name, args_hash)——不含 step 序号：resume 重放时步序可能漂移，
而「同 run 同工具同参数」的结果理应一致，结果级缓存对合法重复调用同样安全。

消费方式（见 orchestration/graph.py 的 _invocation_guard）：
  执行前 lookup（命中 → 直接用缓存观察，fn 不执行）；
  执行后 record（INSERT，撞唯一键 = 并发窗口内已有实例执行过 → 取已有观察）。
表不存在（旧库未迁移）时静默跳过——代码先上、迁移后生效，部署顺序无耦合。
"""
from __future__ import annotations

import hashlib
import json
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def args_hash(args: dict) -> str:
    """稳定参数指纹：sort_keys 后 sha256（同参数同哈希，键序无关）。"""
    raw = json.dumps(args or {}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def lookup(engine: Engine, run_id: str, tool_name: str, args: dict) -> str | None:
    """查缓存观察；命中返回 observation 文本，未命中/表缺失返回 None。"""
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT observation FROM tool_invocation "
                    "WHERE run_id=:r AND tool_name=:t AND args_hash=:h LIMIT 1"
                ),
                {"r": run_id, "t": tool_name, "h": args_hash(args)},
            ).first()
            return str(row[0]) if row else None
    except Exception:  # noqa: BLE001 - 表未迁移/库抖动 → 幂等层降级为不拦截
        logger.debug("tool_invocation lookup 跳过（表缺失或查询失败）", exc_info=True)
        return None


def record(engine: Engine, run_id: str, tool_name: str, args: dict, observation: str) -> None:
    """登记本次执行结果；撞唯一键（并发窗口重复）静默忽略——先到先得。

    不用 MySQL 专属的 INSERT IGNORE（方言锁定、sqlite 测试静默失败）：
    普通 INSERT + 捕获 IntegrityError（两种数据库的唯一键冲突都会映射到它）。
    """
    from sqlalchemy.exc import IntegrityError

    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO tool_invocation "
                    "(run_id, tool_name, args_hash, args_preview, observation) "
                    "VALUES (:r, :t, :h, :p, :o)"
                ),
                {
                    "r": run_id,
                    "t": tool_name,
                    "h": args_hash(args),
                    "p": json.dumps(args or {}, ensure_ascii=False)[:512],
                    "o": str(observation or "")[:24000],
                },
            )
    except IntegrityError:
        logger.debug("tool_invocation 并发撞键（先到先得）run=%s tool=%s", run_id, tool_name)
    except Exception:  # noqa: BLE001 - 登记失败不影响本次任务（降级为无幂等）
        logger.debug("tool_invocation record 跳过（表缺失或写入失败）", exc_info=True)
