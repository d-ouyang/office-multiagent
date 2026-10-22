// 侧栏个人中心：点用户行向上弹出。只展示这个系统真实有的字段。
import { useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, KeyRound, LogOut, Settings } from 'lucide-react';

import { changePassword, getQuota, type LedgerEntry } from '../lib/api';
import { formatLedgerTime, formatTokens } from '../lib/format';
import type { SessionUser } from './AppSidebar';
import { modelDisplayName } from './ModelPicker';

export interface UsageSummary {
  month_tokens: number;
  month_count: number;
  total_tokens: number;
  total_count: number;
}

const ROLE_LABEL: Record<string, string> = {
  admin: '系统管理员',
  staff: '员工',
  user: '成员',
};

function fmt(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—';
  return Math.round(n).toLocaleString('zh-CN');
}

export function AccountPanel(props: {
  user: SessionUser;
  balance: number | null;
  usage: UsageSummary | null;
  modelName: string;
  onClose: () => void;
  onLogout: () => void;
}) {
  const [view, setView] = useState<'home' | 'settings' | 'password' | 'usage'>('home');
  const [ledger, setLedger] = useState<LedgerEntry[] | null>(null);
  const [ledgerError, setLedgerError] = useState<string | null>(null);
  const [confirmLogout, setConfirmLogout] = useState(false);
  const [oldPw, setOldPw] = useState('');
  const [nextPw, setNextPw] = useState('');
  const [again, setAgain] = useState('');
  const [pwError, setPwError] = useState<string | null>(null);
  const [pwOk, setPwOk] = useState(false);
  const [busy, setBusy] = useState(false);
  const role = ROLE_LABEL[props.user.role] ?? props.user.role;
  const initial = (props.user.username || '?').slice(0, 1).toUpperCase();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') props.onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [props]);

  useEffect(() => {
    if (view !== 'usage') return;
    let cancelled = false;
    setLedger(null);
    setLedgerError(null);
    getQuota()
      .then((q) => {
        if (cancelled) return;
        setLedger((q.ledger ?? []).filter((row) => row.settle != null));
      })
      .catch(() => {
        if (!cancelled) setLedgerError('暂时读不到消耗记录');
      });
    return () => {
      cancelled = true;
    };
  }, [view]);

  const submitPassword = async () => {
    setPwError(null);
    if (nextPw.length < 8) {
      setPwError('新密码至少 8 位');
      return;
    }
    if (nextPw !== again) {
      setPwError('两次输入的新密码不一致');
      return;
    }
    setBusy(true);
    try {
      await changePassword(oldPw, nextPw);
      setPwOk(true);
      setOldPw('');
      setNextPw('');
      setAgain('');
    } catch (e) {
      setPwError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="account-pop" role="dialog" aria-label="个人中心">
      {view === 'home' && (
        <>
          <div className="account-head">
            <span className="account-avatar" aria-hidden="true">{initial}</span>
            <div>
              <div className="account-name">{props.user.username}</div>
              <div className="account-sub">{role}</div>
            </div>
          </div>
          <div className="account-card">
            <div className="account-row"><span>登录名</span><b>{props.user.username}</b></div>
            <div className="account-row"><span>工号</span><b>{props.user.employee_id}</b></div>
            <div className="account-row"><span>角色</span><b>{role}</b></div>
          </div>
          <div className="account-card">
            <button type="button" className="account-row account-link" onClick={() => setView('usage')}>
              <span>剩余额度</span>
              <span className="account-row-go">
                <b>{fmt(props.balance)}</b>
                <ChevronRight size={16} className="account-chev" />
              </span>
            </button>
            <div className="account-row">
              <span>本月用量</span>
              <b>{fmt(props.usage?.month_tokens)} · {props.usage?.month_count ?? 0} 次</b>
            </div>
            <div className="account-row">
              <span>累计用量</span>
              <b>{fmt(props.usage?.total_tokens)} · {props.usage?.total_count ?? 0} 次</b>
            </div>
            <p className="account-note">余额不足时新任务会暂停。用量按实际结算入账，余额不会记成负数。</p>
          </div>
          <button type="button" className="account-nav" onClick={() => setView('settings')}>
            <Settings size={16} />
            <span>系统设置</span>
            <ChevronRight size={16} className="account-chev" />
          </button>
          <button type="button" className="account-nav" onClick={() => setView('password')}>
            <KeyRound size={16} />
            <span>修改密码</span>
            <ChevronRight size={16} className="account-chev" />
          </button>
          <div className="account-foot">
            {confirmLogout ? (
              <div className="account-confirm" role="group" aria-label="确认退出">
                <p>确定退出登录？</p>
                <div className="account-confirm-actions">
                  <button type="button" onClick={() => setConfirmLogout(false)}>取消</button>
                  <button type="button" className="danger" onClick={props.onLogout}>退出</button>
                </div>
              </div>
            ) : (
              <button type="button" className="account-nav account-logout-row" onClick={() => setConfirmLogout(true)}>
                <LogOut size={16} />
                <span>退出登录</span>
                <LogOut size={16} className="account-chev" />
              </button>
            )}
          </div>
        </>
      )}
      {view === 'usage' && (
        <>
          <button type="button" className="account-back" onClick={() => setView('home')}>
            <ChevronLeft size={16} /> 消耗详情
          </button>
          <p className="account-note">按实际结算列出。每一行是一次任务的时间、模型和用量。</p>
          {ledgerError && <p className="account-err">{ledgerError}</p>}
          {!ledgerError && ledger === null && <p className="account-note">正在读取…</p>}
          {ledger && ledger.length === 0 && <p className="account-note">还没有消耗记录。</p>}
          {ledger && ledger.length > 0 && (
            <>
              <div className="ledger-head"><span>时间</span><span>模型</span><span>用量</span></div>
              <ul className="ledger-list">
                {ledger.map((row, i) => (
                  <li key={`${row.task_id ?? ''}-${row.created_at ?? ''}-${i}`}>
                    <span className="ledger-time">{formatLedgerTime(row.created_at)}</span>
                    <span className="ledger-model">{modelDisplayName(row.model ?? undefined)}</span>
                    <b>{formatTokens(row.settle ?? undefined)}</b>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
      {view === 'settings' && (
        <>
          <button type="button" className="account-back" onClick={() => setView('home')}>
            <ChevronLeft size={16} /> 系统设置
          </button>
          <div className="account-card">
            <div className="account-row"><span>当前模型</span><b>{props.modelName}</b></div>
            <p className="account-note">在输入条切换模型，会记成当前会话的默认模型。</p>
            <p className="account-note">力度在输入条里选，固定三档：低、高、最大。两档模型会把「低」和「高」合成同一档，只有「最大」对应最高推理力度。没有这个参数的模型不会下发。</p>
          </div>
        </>
      )}
      {view === 'password' && (
        <>
          <button type="button" className="account-back" onClick={() => setView('home')}>
            <ChevronLeft size={16} /> 修改密码
          </button>
          <form
            className="account-form"
            onSubmit={(e) => {
              e.preventDefault();
              void submitPassword();
            }}
          >
            <label>
              当前密码
              <input type="password" value={oldPw} autoComplete="current-password" onChange={(e) => setOldPw(e.target.value)} />
            </label>
            <label>
              新密码
              <input type="password" value={nextPw} autoComplete="new-password" onChange={(e) => setNextPw(e.target.value)} />
            </label>
            <label>
              再输入一次
              <input type="password" value={again} autoComplete="new-password" onChange={(e) => setAgain(e.target.value)} />
            </label>
            {pwError && <p className="account-err">{pwError}</p>}
            {pwOk && <p className="account-ok">密码已更新，其他设备上的旧登录会失效。</p>}
            <button type="submit" className="send" disabled={busy || !oldPw || !nextPw || !again}>
              {busy ? '保存中…' : '保存'}
            </button>
          </form>
        </>
      )}
    </div>
  );
}
