// 管理端最小版（p7.1）：用户列表（含余额）+ 充值 + 最近账本。
// 权限：网关与后端都按 role=admin/superadmin 校验；这里只做入口显隐，不作为安全边界。
import { useCallback, useEffect, useState } from 'react';

import type { SessionUser } from '../components/AppSidebar';
import {
  adminListUsers,
  adminRecharge,
  adminUserLedger,
  type AdminUser,
  type LedgerEntry,
} from '../lib/api';

const REASON: Record<string, string> = {
  reserve: '预扣',
  settle: '结算',
  recharge: '充值',
};

export default function AdminPage({ user, onBack }: { user: SessionUser; onBack: () => void }) {
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
    <div className="admin-page">
      <header className="admin-header">
        <div>
          <h2>管理 · 用户与额度</h2>
          <p className="admin-sub">当前管理员：{user.username}（{user.employee_id} · {user.role}）</p>
        </div>
        <button type="button" className="admin-back" onClick={onBack}>← 返回工作台</button>
      </header>

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
                <tr><th>类型</th><th>预扣</th><th>结算</th><th>备注</th><th>时间</th></tr>
              </thead>
              <tbody>
                {ledger.map((row, i) => (
                  <tr key={i}>
                    <td>{REASON[row.kind ?? 'settle'] ?? row.kind}</td>
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
    </div>
  );
}
