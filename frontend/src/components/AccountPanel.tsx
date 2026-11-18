// 侧栏个人中心：点用户行向上弹出。明细、记忆、设置、改密都交给独立弹窗。
import { useEffect, useState } from 'react';
import { Brain, ChevronRight, KeyRound, LogOut, Settings, Shield } from 'lucide-react';

import type { SessionUser } from './AppSidebar';
import ConfirmDialog from './ui/ConfirmDialog';

export interface UsageSummary {
  month_tokens: number;
  month_count: number;
  total_tokens: number;
  total_count: number;
}

const ROLE_LABEL: Record<string, string> = {
  admin: '系统管理员',
  superadmin: '超级管理员',
  staff: '员工',
  user: '成员',
};

function fmt(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—';
  return Math.round(n).toLocaleString('zh-CN');
}

export type AccountSurface = 'usage' | 'memory' | 'settings' | 'password';

export function AccountPanel(props: {
  user: SessionUser;
  balance: number | null;
  usage: UsageSummary | null;
  onClose: () => void;
  onLogout: () => void;
  onOpenAdmin?: () => void;
  onOpenSurface: (surface: AccountSurface) => void;
}) {
  const [confirmLogout, setConfirmLogout] = useState(false);
  const role = ROLE_LABEL[props.user.role] ?? props.user.role;
  const initial = (props.user.username || '?').slice(0, 1).toUpperCase();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !confirmLogout) props.onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [props, confirmLogout]);

  const open = (surface: AccountSurface) => {
    props.onClose();
    props.onOpenSurface(surface);
  };

  return (
    <div className="account-pop" role="dialog" aria-label="个人中心">
      <div className="account-head">
        <span className="account-avatar" aria-hidden="true">{initial}</span>
        <div className="account-id">
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
        <button type="button" className="account-row account-link" onClick={() => open('usage')}>
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
      <button type="button" className="account-nav" onClick={() => open('memory')}>
        <Brain size={16} />
        <span>长期记忆</span>
        <ChevronRight size={16} className="account-chev" />
      </button>
      <button type="button" className="account-nav" onClick={() => open('settings')}>
        <Settings size={16} />
        <span>系统设置</span>
        <ChevronRight size={16} className="account-chev" />
      </button>
      <button type="button" className="account-nav" onClick={() => open('password')}>
        <KeyRound size={16} />
        <span>修改密码</span>
        <ChevronRight size={16} className="account-chev" />
      </button>
      {props.onOpenAdmin && (
        <button
          type="button"
          className="account-nav"
          onClick={() => {
            props.onClose();
            props.onOpenAdmin?.();
          }}
        >
          <Shield size={16} />
          <span>管理端</span>
          <ChevronRight size={16} className="account-chev" />
        </button>
      )}
      <div className="account-foot">
        <button type="button" className="account-nav account-logout-row" onClick={() => setConfirmLogout(true)}>
          <LogOut size={16} />
          <span>退出登录</span>
        </button>
      </div>
      <ConfirmDialog
        spec={confirmLogout ? {
          title: '确定退出登录？',
          text: '退出后需要重新登录才能继续。',
          confirmText: '退出',
          dangerSoft: true,
        } : null}
        onConfirm={props.onLogout}
        onCancel={() => setConfirmLogout(false)}
      />
    </div>
  );
}
