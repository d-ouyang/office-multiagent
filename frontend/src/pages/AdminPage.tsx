// 管理端（p6.25 → p6.26）：独立路由 /admin + 四个板块
//   用户与额度（列表/充值/流水）· 用量概览（本月消耗 + 近 N 天）· 任务监控 · 系统状态
// 权限：网关与后端都按 role=admin/superadmin 校验；这里只做入口与页面显隐，不是安全边界。
import { useCallback, useEffect, useMemo, useState } from 'react';

import type { SessionUser } from '../components/AppSidebar';
import {
  adminListUsers,
  adminOverview,
  adminRecharge,
  adminTasks,
  adminUsage,
  adminUserLedger,
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

type Tab = 'users' | 'usage' | 'tasks' | 'system';
const TABS: Array<{ key: Tab; label: string }> = [
  { key: 'users', label: '用户与额度' },
  { key: 'usage', label: '用量概览' },
  { key: 'tasks', label: '任务监控' },
  { key: 'system', label: '系统状态' },
];

export default function AdminPage({ user, onBack }: { user: SessionUser; onBack: () => void }) {
  const [tab, setTab] = useState<Tab>('users');
  return (
    <div className="admin-page">
      <header className="admin-header">
        <div>
          <h2>管理端</h2>
          <p className="admin-sub">当前管理员：{user.username}（{user.employee_id} · {user.role}）</p>
        </div>
        <button type="button" className="admin-back" onClick={onBack}>← 返回工作台</button>
      </header>

      <nav className="admin-tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            className={`admin-tab ${tab === t.key ? 'active' : ''}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === 'users' && <UsersTab />}
      {tab === 'usage' && <UsageTab />}
      {tab === 'tasks' && <TasksTab />}
      {tab === 'system' && <SystemTab />}
    </div>
  );
}

/* ------------------------------ 用户与额度 ------------------------------ */

function UsersTab() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [q, setQ] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [amount, setAmount] = useState<Record<number, string>>({});
  const [note, setNote] = useState<Record<number, string>>({});
  const [busyId, setBusyId] = useState<number | null>(null);
  const [ledgerFor, setLedgerFor] = useState<number | null>(null);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);

  const load = useCallback(async (kw: string) => {
    try {
      setUsers(await adminListUsers(kw));
      setError('');
    } catch (e) {
      const msg = (e as Error).message;
      setError(msg === 'FORBIDDEN' ? '需要管理员权限' : `加载失败：${msg}`);
    }
  }, []);

  useEffect(() => {
    void load('');
  }, [load]);

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
      await load(q);
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
        <button type="button" className="admin-btn" onClick={() => void load(q)}>搜索</button>
        <button type="button" className="admin-btn ghost" onClick={() => { setQ(''); void load(''); }}>重置</button>
      </div>

      {error && <div className="banner err">{error}</div>}
      {notice && <div className="banner ok">{notice}</div>}

      <table className="admin-table">
        <thead>
          <tr>
            <th>工号</th>
            <th>用户名</th>
            <th>角色</th>
            <th>余额（token）</th>
            <th>充值数量</th>
            <th>备注</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id}>
              <td>{u.employee_id}</td>
              <td>{u.username}</td>
              <td><span className={`badge ${u.role === 'admin' || u.role === 'superadmin' ? 'agent' : ''}`}>{u.role}</span></td>
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
            <tr><td colSpan={7} className="admin-empty">没有匹配的用户</td></tr>
          )}
        </tbody>
      </table>

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

function UsageTab() {
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

function TasksTab() {
  const [rows, setRows] = useState<AdminTaskRow[]>([]);
  const [filter, setFilter] = useState<string>('');
  const [error, setError] = useState('');

  const load = useCallback(async (status: string) => {
    try {
      setRows(await adminTasks(status || undefined, 30));
      setError('');
    } catch (e) {
      setError(`加载失败：${(e as Error).message}`);
    }
  }, []);

  useEffect(() => {
    void load(filter);
  }, [filter, load]);

  return (
    <>
      <div className="admin-toolbar">
        <select className="admin-search" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">全部状态</option>
          <option value="done">完成</option>
          <option value="paused_user">用户暂停</option>
          <option value="paused_insufficient_quota">配额暂停</option>
          <option value="paused_error">出错暂停</option>
          <option value="resumed">已续跑</option>
        </select>
        <button type="button" className="admin-btn ghost" onClick={() => void load(filter)}>刷新</button>
      </div>
      {error && <div className="banner err">{error}</div>}
      <table className="admin-table">
        <thead>
          <tr><th>时间</th><th>用户</th><th>状态</th><th>原因</th><th>任务摘要</th><th>tokens</th></tr>
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
              <td className="num">{r.tokens_used ? r.tokens_used.toLocaleString() : '—'}</td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={6} className="admin-empty">暂无任务</td></tr>}
        </tbody>
      </table>
    </>
  );
}

/* ------------------------------ 系统状态 ------------------------------ */

function SystemTab() {
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
