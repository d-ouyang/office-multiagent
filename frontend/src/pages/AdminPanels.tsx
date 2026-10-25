// 管理端面板集合（p6.25 → p6.27）：被 AdminApp 的侧边菜单渲染。
// 权限：网关与后端都按 role=admin/superadmin 校验；前端只做显隐，不是安全边界。
import { useCallback, useEffect, useMemo, useState } from 'react';

import { consumeNdjson } from '../lib/consume';
import Select from '../components/ui/Select';
import Pager from '../components/ui/Pager';
import ConfirmDialog, { type ConfirmSpec } from '../components/ui/ConfirmDialog';
import {
  adminListUsers,
  adminOverview,
  adminRecharge,
  adminTasks,
  adminUsage,
  adminUserLedger,
  adminResumeResponse,
  adminModelPools,
  adminCreatePool,
  adminSavePoolModels,
  adminDeletePool,
  adminSetUserPool,
  adminAuditLogs,
  adminRun,
  type AdminRunDetail,
  type ModelPool,
  type AuditRow,
  getHealth,
  type AdminOverview,
  type AdminTaskRow,
  type AdminUser,
  type LedgerEntry,
  type UsagePoint,
} from '../lib/api';

const KIND: Record<string, string> = { reserve: '预扣', settle: '结算', recharge: '充值', task: '任务' };
const STATUS: Record<string, string> = {
  done: '完成',
  resumed: '已续跑',
  failed: '失败',
  pending: '排队',
  running: '运行中',
  paused_user: '用户暂停',
  paused_error: '出错暂停',
  paused_insufficient_quota: '配额暂停',
};
const REASON: Record<string, string> = { quota: '配额不足', user: '用户主动', error: '中途报错', input: '待补充' };

export type AdminTab = 'overview' | 'tasks' | 'runs' | 'users' | 'usage' | 'audit' | 'pools' | 'system';
export type AdminGroup = 'core' | 'ops' | 'advanced';
export const ADMIN_TABS: Array<{ key: AdminTab; label: string; hint: string; group: AdminGroup }> = [
  { key: 'overview', label: '概览', hint: '今天要处理的暂停和关键数字', group: 'core' },
  { key: 'tasks', label: '任务监控', hint: '全局任务 / 暂停原因 / 代续跑', group: 'core' },
  { key: 'runs', label: '运行溯源', hint: '工具序列、产物和校验', group: 'core' },
  { key: 'users', label: '用户与额度', hint: '用户列表 / 充值 / 流水', group: 'ops' },
  { key: 'usage', label: '用量概览', hint: '消耗指标与近 N 天趋势', group: 'ops' },
  { key: 'audit', label: '审计日志', hint: '谁在什么时候做了什么（只读）', group: 'ops' },
  { key: 'pools', label: '模型池', hint: '非日常路径：池定义与用户分配', group: 'advanced' },
  { key: 'system', label: '系统状态', hint: '服务健康 / 模型清单', group: 'advanced' },
];

export const ADMIN_GROUPS: Array<{ id: AdminGroup; label: string }> = [
  { id: 'core', label: '核心' },
  { id: 'ops', label: '次要' },
  { id: 'advanced', label: '高级' },
];

/** 管理端内部跳转。查询参数用来预选用户或过滤任务，hash 决定打开哪一栏。 */
export function goAdmin(tab: AdminTab, query: Record<string, string> = {}) {
  const qs = new URLSearchParams(query).toString();
  window.history.replaceState({}, '', `/admin${qs ? `?${qs}` : ''}#${tab}`);
  window.dispatchEvent(new HashChangeEvent('hashchange'));
}

/* ------------------------------ 用户与额度 ------------------------------ */

export function UsersTab() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [pools, setPools] = useState<ModelPool[]>([]);
  const [q, setQ] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [amount, setAmount] = useState<Record<number, string>>({});
  const [note, setNote] = useState<Record<number, string>>({});
  const [busyId, setBusyId] = useState<number | null>(null);
  const [ledgerFor, setLedgerFor] = useState<number | null>(null);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [focusId, setFocusId] = useState(() => Number(new URLSearchParams(window.location.search).get('user_id') || 0));

  useEffect(() => {
    const sync = () => setFocusId(Number(new URLSearchParams(window.location.search).get('user_id') || 0));
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);

  const load = useCallback(async (kw: string, pg = page, size = pageSize, userId = focusId) => {
    try {
      const data = await adminListUsers(kw, pg, size, userId || undefined);
      setUsers(data.users);
      setTotal(data.total);
      setError('');
    } catch (e) {
      const msg = (e as Error).message;
      setError(msg === 'FORBIDDEN' ? '需要管理员权限' : `加载失败：${msg}`);
    }
  }, [page, pageSize, focusId]);

  useEffect(() => {
    void load('', page, pageSize);
    adminModelPools()
      .then((d) => setPools(d.pools))
      .catch(() => setPools([]));
  }, [load, page, pageSize]);

  /** p6.27c：分配用户的模型池（null=不限制）。 */
  const changePool = async (u: AdminUser, poolId: number | null) => {
    try {
      await adminSetUserPool(u.id, poolId);
      setNotice(`已将 ${u.username} 移到 ${poolId ? pools.find((p) => p.id === poolId)?.name ?? poolId : '不限制'}`);
      await load(q, page, pageSize);
      setTimeout(() => setNotice(''), 3000);
    } catch (e) {
      setError(`分配失败：${(e as Error).message}`);
    }
  };

  const submitRecharge = async (u: AdminUser) => {
    const raw = (amount[u.id] ?? '').trim();
    const value = Number(raw);
    if (!Number.isFinite(value) || value <= 0 || !Number.isInteger(value)) {
      setError('充值数量必须是正整数');
      return;
    }
    setBusyId(u.id);
    setError('');
    try {
      const balance = await adminRecharge(u.id, value, note[u.id]);
      setNotice(`已为 ${u.username} 充值 ${value.toLocaleString()}，当前余额 ${balance.toLocaleString()}`);
      setAmount((prev) => ({ ...prev, [u.id]: '' }));
      await load(q, page, pageSize);
      setTimeout(() => setNotice(''), 4000);
    } catch (e) {
      setError(`充值失败：${(e as Error).message}`);
    } finally {
      setBusyId(null);
    }
  };

  const openLedger = async (u: AdminUser) => {
    if (ledgerFor === u.id) {
      setLedgerFor(null);
      return;
    }
    setLedgerFor(u.id);
    setLedger(await adminUserLedger(u.id, 10));
  };

  return (
    <>
      <div className="admin-toolbar">
        <input
          className="admin-search"
          placeholder="按用户名或工号搜索"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void load(q);
          }}
        />
        <button type="button" className="admin-btn" onClick={() => { setPage(1); void load(q, 1, pageSize); }}>搜索</button>
        <button type="button" className="admin-btn ghost" onClick={() => { setQ(''); setPage(1); void load('', 1, pageSize); }}>重置</button>
      </div>

      {error && <div className="banner err">{error}</div>}
      {notice && <div className="banner ok">{notice}</div>}

      <table className="admin-table">
        <thead>
          <tr>
            <th>工号</th>
            <th>用户名</th>
            <th>角色</th>
            <th>池</th>
            <th>余额（token）</th>
            <th>充值数量</th>
            <th>备注</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className={u.id === focusId ? 'row-active' : ''}>
              <td>{u.employee_id}</td>
              <td>{u.username}</td>
              <td><span className={`badge ${u.role === 'admin' || u.role === 'superadmin' ? 'agent' : ''}`}>{u.role}</span></td>
              <td>
                <Select
                  width={120}
                  value={u.model_pool_id ? String(u.model_pool_id) : ''}
                  placeholder="不限制"
                  options={[
                    { value: '', label: '不限制', hint: '全部模型' },
                    ...pools.map((p) => ({ value: String(p.id), label: p.name, hint: `${p.user_count} 人` })),
                  ]}
                  onChange={(v) => void changePool(u, v ? Number(v) : null)}
                />
              </td>
              <td className="num">{u.balance.toLocaleString()}</td>
              <td>
                <input
                  className="admin-amount"
                  inputMode="numeric"
                  placeholder="如 50000"
                  value={amount[u.id] ?? ''}
                  onChange={(e) => setAmount((prev) => ({ ...prev, [u.id]: e.target.value.replace(/[^\d]/g, '') }))}
                />
              </td>
              <td>
                <input
                  className="admin-note"
                  placeholder="可选"
                  value={note[u.id] ?? ''}
                  onChange={(e) => setNote((prev) => ({ ...prev, [u.id]: e.target.value }))}
                />
              </td>
              <td className="admin-ops">
                <button
                  type="button"
                  className="admin-btn"
                  disabled={busyId === u.id}
                  onClick={() => void submitRecharge(u)}
                >
                  {busyId === u.id ? '充值中…' : '充值'}
                </button>
                <button type="button" className="admin-btn ghost" onClick={() => void openLedger(u)}>
                  {ledgerFor === u.id ? '收起流水' : '流水'}
                </button>
              </td>
            </tr>
          ))}
          {users.length === 0 && (
            <tr><td colSpan={8} className="admin-empty">没有匹配的用户</td></tr>
          )}
        </tbody>
      </table>

      <Pager total={total} page={page} pageSize={pageSize}
        onPage={(p) => setPage(p)}
        onPageSize={(n) => { setPageSize(n); setPage(1); }}
      />

      {ledgerFor !== null && (
        <div className="admin-ledger">
          <h3>最近流水</h3>
          {ledger.length === 0 && <p className="admin-sub">暂无记录</p>}
          {ledger.length > 0 && (
            <table className="admin-table compact">
              <thead>
                <tr><th>类型</th><th>金额</th><th>预扣</th><th>结算</th><th>备注</th><th>时间</th></tr>
              </thead>
              <tbody>
                {ledger.map((row, i) => (
                  <tr key={i}>
                    <td>{KIND[row.kind ?? 'settle'] ?? row.kind}</td>
                    <td className="num">{row.amount ?? '—'}</td>
                    <td className="num">{row.reserve ?? '—'}</td>
                    <td className="num">{row.settle ?? '—'}</td>
                    <td className="admin-muted">{row.note ?? '—'}</td>
                    <td className="admin-muted">{row.created_at ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </>
  );
}

/* ------------------------------ 用量概览 ------------------------------ */

export function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${(n / 10_000).toFixed(1)}w`;
  return n.toLocaleString();
}

export function UsageTab() {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [series, setSeries] = useState<UsagePoint[]>([]);
  const [days, setDays] = useState(7);
  const [error, setError] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const [o, u] = await Promise.all([adminOverview(), adminUsage(days)]);
        setOverview(o);
        setSeries(u.series);
        setError('');
      } catch (e) {
        setError(`加载失败：${(e as Error).message}`);
      }
    })();
  }, [days]);

  const max = useMemo(() => Math.max(1, ...series.map((p) => p.tokens)), [series]);

  return (
    <>
      {error && <div className="banner err">{error}</div>}
      {overview && (
        <div className="admin-cards">
          <Stat label="用户数" value={String(overview.users_total)} />
          <Stat label="余额合计" value={fmtTokens(overview.balance_total)} />
          <Stat label="本月消耗" value={fmtTokens(overview.month_tokens)} hint={`${overview.month_calls} 次任务`} />
          <Stat label="累计充值" value={fmtTokens(overview.recharge_total)} hint={`${overview.recharge_count} 笔`} />
          <Stat label="任务总数" value={String(overview.tasks_total)} hint={`今日 ${overview.tasks_today}`} />
          <Stat label="暂停中" value={String(overview.tasks_paused)} tone={overview.tasks_paused > 0 ? 'warn' : undefined} />
        </div>
      )}
      {overview && overview.tasks_paused > 0 && (
        <p className="admin-sub">
          有 {overview.tasks_paused} 个任务停着。
          <button type="button" className="admin-btn" onClick={() => goAdmin('tasks', { flag: 'paused' })}>
            查看暂停任务
          </button>
        </p>
      )}

      <div className="admin-section-head">
        <h3>近 {days} 天任务消耗</h3>
        <div className="admin-range">
          {[7, 14, 30].map((d) => (
            <button
              key={d}
              type="button"
              className={`admin-tab ${days === d ? 'active' : ''}`}
              onClick={() => setDays(d)}
            >
              {d} 天
            </button>
          ))}
        </div>
      </div>

      {series.length === 0 && <p className="admin-sub">这段时间还没有消耗记录（无 key 时 StubBrain 记 0）。</p>}
      <div className="admin-bars">
        {series.map((p) => (
          <div className="admin-bar-row" key={p.date}>
            <span className="admin-bar-date">{p.date.slice(5)}</span>
            <span className="admin-bar-track">
              <span className="admin-bar-fill" style={{ width: `${Math.max(2, (p.tokens / max) * 100)}%` }} />
            </span>
            <span className="admin-bar-value">{fmtTokens(p.tokens)}</span>
            <span className="admin-muted">{p.calls} 次</span>
          </div>
        ))}
      </div>
    </>
  );
}

function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: 'warn' }) {
  return (
    <div className={`admin-card ${tone ?? ''}`}>
      <span className="admin-card-label">{label}</span>
      <strong className="admin-card-value">{value}</strong>
      {hint && <span className="admin-card-hint">{hint}</span>}
    </div>
  );
}

/* ------------------------------ 任务监控 ------------------------------ */

const TASK_STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'done', label: '完成' },
  { value: 'paused_user', label: '用户暂停' },
  { value: 'paused_insufficient_quota', label: '配额暂停' },
  { value: 'paused_error', label: '出错暂停' },
  { value: 'resumed', label: '已续跑' },
];

export function TasksTab() {
  const [rows, setRows] = useState<AdminTaskRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [filter, setFilter] = useState<string>(() => new URLSearchParams(window.location.search).get('status') || '');
  const [flag, setFlag] = useState<string>(() => new URLSearchParams(window.location.search).get('flag') || '');
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');
  const [result, setResult] = useState<{ title: string; lines: string[] } | null>(null);
  const [resuming, setResuming] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<AdminTaskRow | null>(null);

  const load = useCallback(async (status: string, pg = page, size = pageSize) => {
    try {
      const data = await adminTasks(status || undefined, pg, size, flag || undefined);
      setRows(data.tasks);
      setTotal(data.total);
      setError('');
    } catch (e) {
      setError(`加载失败：${(e as Error).message}`);
    }
  }, [page, pageSize, flag]);

  useEffect(() => {
    const sync = () => {
      const q = new URLSearchParams(window.location.search);
      setFilter(q.get('status') || '');
      setFlag(q.get('flag') || '');
    };
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);

  useEffect(() => {
    void load(filter, page, pageSize);
  }, [filter, page, pageSize, load]);

  /** p6.28d：确认后代续跑——流式消费只取结果，完成后弹结果窗（不再是"点了啥都看不见"）。 */
  const resumeConfirmed = async (r: AdminTaskRow) => {
    setConfirm(null);
    setResuming(r.id);
    setMsg('');
    try {
      const res = await adminResumeResponse(r.id);
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(String(d?.detail?.message ?? `HTTP ${res.status}`));
      }
      let doneStatus = '';
      let tokens = 0;
      let newRunId = '';
      let errText = '';
      await consumeNdjson(res, (ev) => {
        if (ev.type === 'done') {
          doneStatus = String(ev.data.status ?? '');
          tokens = Number(ev.data.tokens_used ?? 0);
          newRunId = String(ev.run_id ?? '');
        }
        if (ev.type === 'error') errText = String(ev.data?.message ?? '');
      });
      if (errText) throw new Error(errText);
      const lines = [
        `任务：${(r.text || '').slice(0, 60)}`,
        `归属用户：${r.username ?? '—'}`,
        `终态：${STATUS[doneStatus] ?? (doneStatus || '完成')}`,
        tokens ? `消耗：${tokens.toLocaleString()} tokens（记在该用户账上）` : '消耗：—',
        newRunId ? `新任务 ID：${newRunId}` : '',
      ].filter(Boolean);
      setResult({ title: '代续跑已完成', lines });
      setMsg(`已代 ${r.username ?? '用户'} 续跑，终态 ${STATUS[doneStatus] ?? doneStatus}`);
      await load(filter, page, pageSize);
    } catch (e) {
      setResult({ title: '代续跑未完成', lines: [(e as Error).message] });
    } finally {
      setResuming(null);
    }
  };

  const confirmSpec: ConfirmSpec | null = confirm
    ? {
        title: '确认代该用户续跑这个任务？',
        text: '续跑 = 按原请求【重新跑一遍】，不是从暂停处接着跑。',
        bullets: [
          `任务：${(confirm.text || '').slice(0, 50)}`,
          `归属：${confirm.username ?? '—'}（${confirm.pause_reason ? REASON[confirm.pause_reason] ?? confirm.pause_reason : '未知'}暂停）`,
          '已完成的步骤会重新执行，消耗记在原用户账上',
          `操作会留痕：审计日志记录操作人（你）与原任务 ID ${confirm.id.slice(0, 12)}…`,
        ],
        confirmText: '确认续跑',
        danger: true,
      }
    : null;

  return (
    <>
      <div className="admin-toolbar">
        <Select
          width={150}
          value={filter}
          placeholder="全部状态"
          options={TASK_STATUS_OPTIONS}
          onChange={(v) => { setFilter(v); setPage(1); }}
        />
        <Select
          width={160}
          value={flag}
          placeholder="全部痕迹"
          options={[
            { value: '', label: '全部痕迹' },
            { value: 'paused', label: '暂停' },
            { value: 'rag', label: '曾检索知识库' },
            { value: 'validation', label: '数字未对齐' },
            { value: 'no_artifact', label: '无产物' },
          ]}
          onChange={(v) => { setFlag(v); setPage(1); }}
        />
        <button type="button" className="admin-btn ghost" onClick={() => void load(filter, page, pageSize)}>刷新</button>
      </div>
      {error && <div className="banner err">{error}</div>}
      {msg && <div className="banner ok">{msg}</div>}
      <table className="admin-table">
        <thead>
          <tr><th>时间</th><th>用户</th><th>状态</th><th>原因</th><th>任务摘要</th><th>工具</th><th>tokens</th><th>操作</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td className="admin-muted">{r.created_at ? r.created_at.replace('T', ' ').slice(5, 19) : '—'}</td>
              <td>{r.username ?? '—'}</td>
              <td>
                <span className={`badge ${r.status.startsWith('paused') || r.status === 'failed' ? 'warn' : 'agent'}`}>
                  {STATUS[r.status] ?? r.status}
                </span>
              </td>
              <td className="admin-muted">{r.pause_reason ? REASON[r.pause_reason] ?? r.pause_reason : '—'}</td>
              <td className="admin-task-text" title={r.text}>{r.text || '—'}</td>
              <td className="admin-muted" title={r.tool_summary || '无 trace'}>{r.tool_summary || (r.has_trace === false ? '无 trace' : '—')}</td>
              <td className="num">{r.tokens_used ? r.tokens_used.toLocaleString() : '—'}</td>
              <td className="admin-ops">
                {r.pause_reason === 'quota' && r.user_id ? (
                  <button type="button" className="admin-btn ghost" onClick={() => goAdmin('users', { user_id: String(r.user_id) })}>
                    去充值
                  </button>
                ) : null}
                {r.status.startsWith('paused') || r.status === 'failed' ? (
                  <button
                    type="button"
                    className="admin-btn"
                    disabled={resuming === r.id}
                    onClick={() => setConfirm(r)}
                    title="以管理员身份替该用户重跑（消耗记在原用户头上）"
                  >
                    {resuming === r.id ? '续跑中…' : '代续跑'}
                  </button>
                ) : (
                  <span className="admin-muted">—</span>
                )}
              </td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={8} className="admin-empty">暂无任务</td></tr>}
        </tbody>
      </table>
      <Pager total={total} page={page} pageSize={pageSize}
        onPage={(p) => setPage(p)}
        onPageSize={(n) => { setPageSize(n); setPage(1); }}
      />
      <ConfirmDialog
        spec={confirmSpec}
        busy={resuming !== null}
        onConfirm={() => confirm && void resumeConfirmed(confirm)}
        onCancel={() => setConfirm(null)}
      />
      {result && (
        <div className="ui-confirm-mask" onClick={() => setResult(null)}>
          <div className="ui-confirm" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <h3>{result.title}</h3>
            <ul className="ui-confirm-bullets">
              {result.lines.map((l, i) => <li key={i}>{l}</li>)}
            </ul>
            <div className="ui-confirm-actions">
              <button type="button" className="admin-btn" onClick={() => setResult(null)}>知道了</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

/* ------------------------------ 系统状态 ------------------------------ */

export function SystemTab() {
  const [health, setHealth] = useState<{ status: string; services?: Record<string, { ok: boolean; detail?: string | null }> } | null>(null);
  const [models, setModels] = useState<Array<{ id: string; name?: string; in_dialogue?: boolean }>>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const [h, m] = await Promise.all([
          getHealth(),
          fetch('/api/v1/models').then((r) => r.json()).catch(() => ({ models: [] })),
        ]);
        setHealth(h);
        setModels(m.models ?? []);
      } catch (e) {
        setError(`加载失败：${(e as Error).message}`);
      }
    })();
  }, []);

  const services = health?.services ?? {};
  return (
    <>
      {error && <div className="banner err">{error}</div>}
      <p className="admin-sub">系统状态放在高级区。日常先看概览上的健康点。</p>
      <div className="admin-cards">
        <Stat
          label="服务状态"
          value={health?.status === 'ok' ? '正常' : health ? '异常' : '…'}
          tone={health?.status === 'ok' ? undefined : 'warn'}
        />
        {Object.entries(services).map(([name, s]) => (
          <Stat key={name} label={name} value={s.ok ? '正常' : '异常'} hint={s.detail ?? undefined} tone={s.ok ? undefined : 'warn'} />
        ))}
        <Stat label="对话模型" value={String(models.filter((m) => m.in_dialogue !== false).length)} />
      </div>
      {models.length > 0 && (
        <div className="admin-ledger">
          <h3>已注册模型</h3>
          <table className="admin-table compact">
            <thead><tr><th>ID</th><th>名称</th></tr></thead>
            <tbody>
              {models.map((m) => (
                <tr key={m.id}><td>{m.id}</td><td className="admin-muted">{m.name ?? '—'}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

/* ------------------------------ 模型池（p6.27c） ------------------------------ */

export function ModelPoolsTab() {
  const [pools, setPools] = useState<ModelPool[]>([]);
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [draft, setDraft] = useState<Record<string, boolean>>({});
  const [newName, setNewName] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const { pools } = await adminModelPools();
      setPools(pools);
      setError('');
      setCurrentId((prev) => (prev && pools.some((p) => p.id === prev) ? prev : pools[0]?.id ?? null));
    } catch (e) {
      setError(`加载失败：${(e as Error).message}`);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const current = pools.find((p) => p.id === currentId) ?? null;

  // 选中池变化时，把它的模型矩阵装进草稿（未保存的修改以草稿为准）
  useEffect(() => {
    if (!current) return;
    setDraft(Object.fromEntries(current.models.map((m) => [m.model_name, m.enabled])));
  }, [current]);

  const save = async () => {
    if (!current) return;
    setBusy(true);
    setError('');
    try {
      await adminSavePoolModels(
        current.id,
        Object.entries(draft).map(([model_name, enabled]) => ({ model_name, enabled })),
      );
      setNotice(`已保存「${current.name}」的模型成员`);
      await load();
      setTimeout(() => setNotice(''), 3000);
    } catch (e) {
      setError(`保存失败：${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const createPool = async () => {
    const name = newName.trim();
    if (!name) return;
    setBusy(true);
    setError('');
    try {
      await adminCreatePool(name);
      setNewName('');
      await load();
      setNotice(`已创建池「${name}」`);
      setTimeout(() => setNotice(''), 3000);
    } catch (e) {
      setError(`创建失败：${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const removePool = async (p: ModelPool) => {
    setBusy(true);
    setError('');
    try {
      await adminDeletePool(p.id);
      await load();
      setNotice(`已删除池「${p.name}」`);
      setTimeout(() => setNotice(''), 3000);
    } catch (e) {
      setError(`删除失败：${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const enabledCount = Object.values(draft).filter(Boolean).length;

  return (
    <>
      {error && <div className="banner err">{error}</div>}
      {notice && <div className="banner ok">{notice}</div>}
      <p className="admin-sub">模型池不是日常运营路径。用户已经能对话时，不必先来这里配池。</p>
      <div className="admin-pool-layout">
        <section className="admin-pool-list">
          <h3>模型池</h3>
          <div className="admin-toolbar">
            <input
              className="admin-search"
              placeholder="新池名（如 finance）"
              value={newName}
              maxLength={32}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void createPool();
              }}
            />
            <button type="button" className="admin-btn" disabled={busy || !newName.trim()} onClick={() => void createPool()}>
              新建
            </button>
          </div>
          <table className="admin-table compact">
            <thead><tr><th>池</th><th>用户数</th><th /></tr></thead>
            <tbody>
              {pools.map((p) => (
                <tr key={p.id} className={p.id === currentId ? 'row-active' : ''}>
                  <td>
                    <button type="button" className="admin-pool-name" onClick={() => setCurrentId(p.id)}>
                      {p.name}
                    </button>
                  </td>
                  <td className="num">{p.user_count}</td>
                  <td className="admin-ops">
                    <button
                      type="button"
                      className="admin-btn ghost"
                      disabled={busy || p.user_count > 0}
                      title={p.user_count > 0 ? '还有用户在该池，先移走再删' : '删除该池'}
                      onClick={() => void removePool(p)}
                    >
                      删除
                    </button>
                  </td>
                </tr>
              ))}
              {pools.length === 0 && <tr><td colSpan={3} className="admin-empty">暂无池</td></tr>}
            </tbody>
          </table>
          <p className="admin-sub">
            池名与 models.yaml 的 pool_ids 对齐（default/staff/admin）；勾选即显式配置，未配置的模型回落 yaml 默认。
          </p>
        </section>

        <section className="admin-pool-models">
          {!current && <p className="admin-sub">先在左侧选择或新建一个池。</p>}
          {current && (
            <>
              <div className="admin-section-head">
                <h3>「{current.name}」可见的模型（{enabledCount} 个）</h3>
                <button type="button" className="admin-btn" disabled={busy} onClick={() => void save()}>
                  {busy ? '保存中…' : '保存成员'}
                </button>
              </div>
              <div className="admin-pool-grid">
                {current.models.map((m) => (
                  <label key={m.model_name} className={`admin-pool-item ${draft[m.model_name] ? 'on' : ''}`}>
                    <input
                      type="checkbox"
                      checked={!!draft[m.model_name]}
                      onChange={(e) =>
                        setDraft((prev) => ({ ...prev, [m.model_name]: e.target.checked }))
                      }
                    />
                    <span>{m.model_name}</span>
                  </label>
                ))}
              </div>
              <p className="admin-sub">
                用户分配在「用户与额度」板块的"池"列；保存后即时生效（下次 /models 请求即按新成员过滤）。
              </p>
            </>
          )}
        </section>
      </div>
    </>
  );
}

/* ------------------------------ 审计日志（p6.28a） ------------------------------ */

const TARGET_LABEL: Record<string, string> = {
  auth: '登录态',
  user: '用户',
  task: '任务',
  pool: '模型池',
  admin: '管理员',
};

/** detail 按动作翻译成人话（排查的人不该自己翻译键名）。 */
export function renderDetail(action: string, detail: Record<string, unknown> | null): string[] {
  if (!detail) return [];
  const out: string[] = [];
  const push = (k: string, v: unknown) => out.push(`${k} ${v ?? '—'}`);
  if (action === 'admin.recharge') {
    push('充值', `${Number(detail.amount ?? 0).toLocaleString()} tokens`);
    push('充值后余额', Number(detail.balance_after ?? 0).toLocaleString());
    if (detail.note) push('备注', String(detail.note));
  } else if (action === 'admin.user.pool.change') {
    push('新模型池', detail.model_pool_id === null ? '不限制' : `#${detail.model_pool_id}`);
  } else if (action === 'admin.task.resume') {
    push('原任务归属', String(detail.owner_username ?? '—'));
    push('任务内容', String(detail.text ?? '—'));
  } else if (action === 'admin.pool.models.set') {
    const enabled = Array.isArray(detail.enabled) ? detail.enabled : [];
    push('启用模型', `${enabled.length} 个`);
  } else if (action === 'admin.password.change') {
    push('结果', '已修改，旧登录态已全部失效');
  } else if (action === 'admin.login.failure') {
    push('原因', detail.reason === 'bad_credentials' ? '用户名或密码错误' : String(detail.reason ?? '—'));
    if (detail.admin === false) push('说明', '账密正确但非管理员角色');
  } else if (action === 'admin.login.success') {
    push('角色', String(detail.role ?? '—'));
  }
  return out;
}

export function AuditTab() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [action, setAction] = useState('');
  const [targetType, setTargetType] = useState('');
  const [keyword, setKeyword] = useState('');
  const [actions, setActions] = useState<Array<{ value: string; label: string }>>([]);
  const [targetTypes, setTargetTypes] = useState<string[]>([]);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const data = await adminAuditLogs({ action: action || undefined, target_type: targetType || undefined, keyword, page, page_size: pageSize });
      setRows(data.logs);
      setTotal(data.total);
      if (data.actions.length) setActions(data.actions);
      if (data.target_types.length) setTargetTypes(data.target_types);
      setError('');
    } catch (e) {
      setError(`加载失败：${(e as Error).message}`);
    }
  }, [action, targetType, keyword, page, pageSize]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <div className="admin-toolbar">
        <Select
          width={170}
          value={action}
          placeholder="全部动作"
          options={[{ value: '', label: '全部动作' }, ...actions.map((a) => ({ value: a.value, label: a.label }))]}
          onChange={(v) => { setAction(v); setPage(1); }}
        />
        <Select
          width={130}
          value={targetType}
          placeholder="全部对象"
          options={[
            { value: '', label: '全部对象' },
            ...targetTypes.map((t) => ({ value: t, label: TARGET_LABEL[t] ?? t })),
          ]}
          onChange={(v) => { setTargetType(v); setPage(1); }}
        />
        <input
          className="admin-search"
          style={{ flex: '0 0 220px' }}
          placeholder="操作人 / 对象 / 关键词"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { setPage(1); void load(); }
          }}
        />
        <button type="button" className="admin-btn ghost" onClick={() => void load()}>刷新</button>
      </div>

      <p className="admin-sub">
        审计日志只读：没有修改/删除入口（后端仓储层也不提供）。登记的动作见下拉候选；敏感内容（密码/token）在写入时就会被拒绝。
      </p>

      {error && <div className="banner err">{error}</div>}
      <table className="admin-table">
        <thead>
          <tr><th>时间</th><th>操作人</th><th>动作</th><th>对象</th><th>明细</th><th>IP</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td className="admin-muted nowrap">{(r.created_at ?? '').replace('T', ' ').slice(5, 19)}</td>
              <td>
                {r.actor_username}
                {r.actor_role && <span className="admin-muted"> · {r.actor_role}</span>}
              </td>
              <td><span className="badge agent">{r.action_label ?? r.action}</span></td>
              <td className="admin-muted">
                {TARGET_LABEL[r.target_type] ?? r.target_type}
                {r.target_label ? ` · ${r.target_label}` : ''}
              </td>
              <td>
                <div className="audit-detail">
                  {renderDetail(r.action, r.detail).length === 0 && <span>—</span>}
                  {renderDetail(r.action, r.detail).map((line, i) => (
                    <span key={i}>{line}</span>
                  ))}
                </div>
              </td>
              <td className="admin-muted">{r.ip ?? '—'}</td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={6} className="admin-empty">暂无审计记录</td></tr>}
        </tbody>
      </table>
      <Pager total={total} page={page} pageSize={pageSize}
        onPage={(p) => setPage(p)}
        onPageSize={(n) => { setPageSize(n); setPage(1); }}
      />
    </>
  );
}

const ROLE_LABEL: Record<string, string> = {
  admin: '系统管理员',
  superadmin: '超级管理员',
  staff: '员工',
  user: '成员',
};

export function roleLabel(role: string): string {
  return ROLE_LABEL[role] ?? role;
}

export function OverviewTab() {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [health, setHealth] = useState<string>('');
  const [error, setError] = useState('');

  useEffect(() => {
    adminOverview().then(setOverview).catch((e) => setError((e as Error).message));
    getHealth().then((h) => setHealth(h.status)).catch(() => setHealth('error'));
  }, []);

  const reasons = overview?.paused_by_reason ?? {};
  return (
    <>
      {error && <div className="banner err">{error}</div>}
      <p className="admin-health">
        <i className={health === 'ok' ? 'ok' : 'bad'} />
        {health === 'ok' ? '服务正常' : health ? '服务异常' : '正在查看服务'}
      </p>
      {overview && (
        <div className="admin-cards">
          <Stat label="暂停中" value={String(overview.tasks_paused)} tone={overview.tasks_paused > 0 ? 'warn' : undefined} />
          <Stat label="近 7 日失败" value={String(overview.tasks_failed_7d ?? 0)} />
          <Stat label="完成率" value={overview.completion_rate == null ? '—' : `${Math.round(overview.completion_rate * 100)}%`} />
          <Stat label="数字未对齐" value={String(overview.validation_mismatches ?? 0)} />
          <Stat label="平均工具步数" value={overview.avg_tool_steps == null ? '—' : String(overview.avg_tool_steps)} />
          <Stat label="今日任务" value={String(overview.tasks_today)} />
        </div>
      )}
      <h3>待办</h3>
      <ul className="admin-todo">
        <li>
          <button type="button" onClick={() => goAdmin('tasks', { flag: 'paused' })}>
            暂停任务 {overview?.tasks_paused ?? '…'}
          </button>
          <span>{Object.entries(reasons).map(([k, n]) => `${REASON[k] ?? k} ${n}`).join(' · ') || '暂无暂停'}</span>
        </li>
        <li>
          <button type="button" onClick={() => goAdmin('runs', { flag: 'validation' })}>数字未对齐</button>
          <span>只观察，不拦截回答</span>
        </li>
        <li>
          <button type="button" onClick={() => goAdmin('runs', { flag: 'rag' })}>曾检索知识库</button>
          <span>核对调用身份是不是服务号</span>
        </li>
      </ul>
    </>
  );
}

export function RunsTab() {
  const [rows, setRows] = useState<AdminTaskRow[]>([]);
  const [flag, setFlag] = useState(() => new URLSearchParams(window.location.search).get('flag') || '');
  const [error, setError] = useState('');
  const [detail, setDetail] = useState<AdminRunDetail | null>(null);

  const load = useCallback(async (nextFlag: string) => {
    try {
      const data = await adminTasks(undefined, 1, 20, nextFlag || undefined);
      setRows(data.tasks);
      setError('');
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void load(flag);
  }, [flag, load]);

  useEffect(() => {
    const sync = () => setFlag(new URLSearchParams(window.location.search).get('flag') || '');
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);

  return (
    <>
      <div className="admin-toolbar">
        <Select
          width={180}
          value={flag}
          placeholder="全部"
          options={[
            { value: '', label: '最近运行' },
            { value: 'paused', label: '暂停' },
            { value: 'rag', label: '曾检索知识库' },
            { value: 'validation', label: '数字未对齐' },
            { value: 'no_artifact', label: '无产物' },
          ]}
          onChange={setFlag}
        />
      </div>
      {error && <div className="banner err">{error}</div>}
      <table className="admin-table">
        <thead>
          <tr><th>时间</th><th>用户</th><th>状态</th><th>工具序列</th><th /></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td className="admin-muted">{r.created_at ? r.created_at.replace('T', ' ').slice(5, 16) : '—'}</td>
              <td>{r.username ?? '—'}</td>
              <td>{STATUS[r.status] ?? r.status}</td>
              <td>{r.tool_summary || (r.has_trace ? '—' : '无 trace')}</td>
              <td><button type="button" className="admin-btn ghost" onClick={() => void adminRun(r.id).then(setDetail).catch((e) => setError((e as Error).message))}>详情</button></td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={5} className="admin-empty">没有符合条件的运行</td></tr>}
        </tbody>
      </table>
      {detail && (
        <div className="ui-confirm-mask" onClick={() => setDetail(null)}>
          <div className="ui-confirm admin-run-detail" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <h3>运行 {detail.id.slice(0, 12)}</h3>
            <p>{detail.text}</p>
            <ul className="ui-confirm-bullets">
              <li>用户：{detail.username ?? '—'} · 模型：{detail.model || '—'}</li>
              <li>状态：{STATUS[detail.status] ?? detail.status} · 消耗：{detail.tokens_used || '—'}</li>
              <li>工具：{detail.tools.length ? detail.tools.join(' → ') : '无 trace'}</li>
              <li>产物：{detail.artifacts.length ? detail.artifacts.join('、') : '无'}</li>
              <li className={detail.identity_mismatch ? 'warn-text' : ''}>
                知识库身份：调用 {detail.rag_username || '—'}，办公用户 {detail.office_username || detail.username || '—'}
                {detail.identity_mismatch ? '（不一致）' : ''}
              </li>
              {detail.validation_note && <li>校验：{detail.validation_note}</li>}
            </ul>
            <div className="ui-confirm-actions">
              <button type="button" className="admin-btn" onClick={() => setDetail(null)}>关闭</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
