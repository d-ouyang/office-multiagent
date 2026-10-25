import { useCallback, useEffect, useState } from 'react';

import Pager from '../components/ui/Pager';
import Select from '../components/ui/Select';
import {
  adminListUsers,
  adminModelPools,
  adminRecharge,
  adminSetUserPool,
  adminUserLedger,
  type AdminUser,
  type LedgerEntry,
  type ModelPool,
} from '../lib/api';
import { fmtShanghai, fmtTokens, KIND } from './format';
import { goAdmin } from './nav';

export default function UsersTab() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [pools, setPools] = useState<ModelPool[]>([]);
  const [q, setQ] = useState('');
  const [appliedQ, setAppliedQ] = useState('');
  const [balanceMin, setBalanceMin] = useState('');
  const [balanceMax, setBalanceMax] = useState('');
  const [appliedMin, setAppliedMin] = useState('');
  const [appliedMax, setAppliedMax] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [focusId, setFocusId] = useState(() => Number(new URLSearchParams(window.location.search).get('user_id') || 0));
  const [rechargeUser, setRechargeUser] = useState<AdminUser | null>(null);
  const [ledgerUser, setLedgerUser] = useState<AdminUser | null>(null);

  useEffect(() => {
    const sync = () => setFocusId(Number(new URLSearchParams(window.location.search).get('user_id') || 0));
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);

  const load = useCallback(async (kw: string, pg = page, size = pageSize, userId = focusId) => {
    try {
      const min = appliedMin.trim() ? Number(appliedMin) : undefined;
      const max = appliedMax.trim() ? Number(appliedMax) : undefined;
      const data = await adminListUsers(kw, pg, size, userId || undefined, min, max);
      setUsers(data.users);
      setTotal(data.total);
      setError('');
    } catch (e) {
      const msg = (e as Error).message;
      setError(msg === 'FORBIDDEN' ? '需要管理员权限' : `加载失败：${msg}`);
    }
  }, [page, pageSize, focusId, appliedMin, appliedMax]);

  useEffect(() => {
    void load(appliedQ, page, pageSize);
    adminModelPools().then((d) => setPools(d.pools)).catch(() => setPools([]));
  }, [load, page, pageSize, appliedQ]);

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

  const search = () => {
    setAppliedQ(q);
    setAppliedMin(balanceMin);
    setAppliedMax(balanceMax);
    setPage(1);
  };

  return (
    <div className="list-page">
      <div className="admin-toolbar wrap">
        <input
          className="admin-search"
          placeholder="精确搜索用户名或工号"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') search(); }}
        />
        <input
          className="admin-search narrow"
          inputMode="numeric"
          placeholder="余额 ≥"
          value={balanceMin}
          onChange={(e) => setBalanceMin(e.target.value.replace(/[^\d-]/g, ''))}
          onKeyDown={(e) => { if (e.key === 'Enter') search(); }}
        />
        <input
          className="admin-search narrow"
          inputMode="numeric"
          placeholder="余额 ≤"
          value={balanceMax}
          onChange={(e) => setBalanceMax(e.target.value.replace(/[^\d-]/g, ''))}
          onKeyDown={(e) => { if (e.key === 'Enter') search(); }}
        />
        <button type="button" className="admin-btn" onClick={search}>搜索</button>
        <button type="button" className="admin-btn ghost" onClick={() => { setQ(''); setAppliedQ(''); setBalanceMin(''); setBalanceMax(''); setAppliedMin(''); setAppliedMax(''); setPage(1); }}>重置</button>
      </div>

      {error && <div className="banner err">{error}</div>}
      {notice && <div className="banner ok">{notice}</div>}

      <div className="table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>工号</th>
              <th>用户名</th>
              <th>角色</th>
              <th>池</th>
              <th>余额（token）</th>
              <th>总使用量</th>
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
                <td className="num">{fmtTokens(u.total_used ?? 0)}</td>
                <td className="admin-ops">
                  <button type="button" className="admin-btn" onClick={() => setRechargeUser(u)}>充值</button>
                  <button type="button" className="admin-btn ghost" onClick={() => setLedgerUser(u)}>流水</button>
                </td>
              </tr>
            ))}
            {users.length === 0 && <tr><td colSpan={7} className="admin-empty">没有匹配的用户</td></tr>}
          </tbody>
        </table>
      </div>

      <Pager total={total} page={page} pageSize={pageSize}
        onPage={(p) => setPage(p)}
        onPageSize={(n) => { setPageSize(n); setPage(1); }}
      />

      {rechargeUser && (
        <RechargeModal
          user={rechargeUser}
          onClose={() => setRechargeUser(null)}
          onDone={async (msg) => {
            setNotice(msg);
            setRechargeUser(null);
            await load(q, page, pageSize);
            setTimeout(() => setNotice(''), 4000);
          }}
          onError={setError}
        />
      )}
      {ledgerUser && <LedgerDrawer user={ledgerUser} onClose={() => setLedgerUser(null)} />}
    </div>
  );
}

function RechargeModal({
  user,
  onClose,
  onDone,
  onError,
}: {
  user: AdminUser;
  onClose: () => void;
  onDone: (msg: string) => Promise<void>;
  onError: (msg: string) => void;
}) {
  const [amount, setAmount] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const value = Number(amount.trim());
    if (!Number.isFinite(value) || value <= 0 || !Number.isInteger(value)) {
      onError('充值数量必须是正整数');
      return;
    }
    setBusy(true);
    try {
      const balance = await adminRecharge(user.id, value, note);
      await onDone(`已为 ${user.username} 充值 ${value.toLocaleString()}，当前余额 ${balance.toLocaleString()}`);
    } catch (e) {
      onError(`充值失败：${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ui-confirm-mask" onClick={onClose}>
      <div className="ui-confirm" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <h3>给 {user.username} 充值</h3>
        <p className="admin-sub">工号 {user.employee_id} · 当前余额 {user.balance.toLocaleString()}</p>
        <label className="admin-field">
          充值数量
          <input className="admin-amount" inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d]/g, ''))} placeholder="如 50000" />
        </label>
        <label className="admin-field">
          备注
          <input className="admin-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="可选" />
        </label>
        <div className="ui-confirm-actions">
          <button type="button" className="admin-btn ghost" onClick={onClose}>取消</button>
          <button type="button" className="admin-btn" disabled={busy} onClick={() => void submit()}>{busy ? '充值中…' : '确认充值'}</button>
        </div>
      </div>
    </div>
  );
}

function LedgerDrawer({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const [rows, setRows] = useState<LedgerEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  useEffect(() => {
    adminUserLedger(user.id, page, pageSize).then((data) => {
      setRows(data.ledger);
      setTotal(data.total);
    }).catch(() => {
      setRows([]);
      setTotal(0);
    });
  }, [user.id, page, pageSize]);

  const showReserve = rows.some((row) => row.kind === 'reserve' || (row.reserve && !row.settle && !row.amount));

  return (
    <div className="admin-drawer-mask" onClick={onClose}>
      <aside className="admin-drawer" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <header className="admin-drawer-head">
          <div>
            <h3>{user.username} 的流水</h3>
            <p className="admin-sub">工号 {user.employee_id}</p>
          </div>
          <button type="button" className="admin-btn ghost" onClick={onClose}>关闭</button>
        </header>
        <div className="admin-drawer-body">
          <table className="admin-table compact">
            <thead>
              <tr>
                <th>类型</th>
                <th>充值数量</th>
                <th>消耗数量</th>
                {showReserve && <th>预扣</th>}
                <th>备注</th>
                <th>时间</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={`${row.task_id ?? i}-${row.created_at ?? i}`}>
                  <td>{KIND[row.kind ?? 'settle'] ?? row.kind}</td>
                  <td className="num">{row.kind === 'recharge' ? (row.amount ?? '—') : '—'}</td>
                  <td className="num">{row.settle ?? '—'}</td>
                  {showReserve && <td className="num">{row.reserve ?? '—'}</td>}
                  <td className="admin-muted">{row.note ?? '—'}</td>
                  <td className="admin-muted nowrap">{fmtShanghai(row.created_at)}</td>
                  <td>
                    {row.task_id ? (
                      <button
                        type="button"
                        className="admin-btn ghost"
                        onClick={() => goAdmin('tasks', { task_id: String(row.task_id), open: '1' })}
                      >
                        详情
                      </button>
                    ) : '—'}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={showReserve ? 7 : 6} className="admin-empty">暂无记录</td></tr>}
            </tbody>
          </table>
          <Pager total={total} page={page} pageSize={pageSize}
            onPage={setPage}
            onPageSize={(n) => { setPageSize(n); setPage(1); }}
          />
        </div>
      </aside>
    </div>
  );
}
