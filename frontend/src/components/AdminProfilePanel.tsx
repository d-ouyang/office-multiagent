// 管理端个人中心（p6.27）：管理员信息 + 改密 + 退出。
// 注意：管理端 token 与工作台 token 相互独立，退出只退管理端。
import { useState } from 'react';

import { adminChangePassword, adminClearToken, adminLogout, type LoginUser } from '../lib/api';

export default function AdminProfilePanel({
  user,
  onClose,
  onLogout,
}: {
  user: LoginUser;
  onClose: () => void;
  onLogout: () => void;
}) {
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setNotice('');
    if (newPassword.length < 6) {
      setError('新密码至少 6 位');
      return;
    }
    if (newPassword !== confirm) {
      setError('两次输入的新密码不一致');
      return;
    }
    setBusy(true);
    try {
      await adminChangePassword(oldPassword, newPassword);
      setNotice('密码已修改，管理端登录态已自动更新');
      setOldPassword('');
      setNewPassword('');
      setConfirm('');
    } catch (err) {
      setError((err as Error).message || '修改失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="admin-profile-mask" onClick={onClose}>
      <div className="admin-profile" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <header className="admin-profile-head">
          <span className="account-avatar" aria-hidden="true">
            {(user.username || '?').slice(0, 1).toUpperCase()}
          </span>
          <div>
            <strong>{user.username}</strong>
            <p className="admin-sub">
              {user.employee_id} · {user.role}
            </p>
          </div>
          <button type="button" className="admin-btn ghost admin-profile-close" onClick={onClose}>
            关闭
          </button>
        </header>

        {notice && <div className="banner ok">{notice}</div>}
        {error && <div className="banner err">{error}</div>}

        <form className="admin-profile-form" onSubmit={submit}>
          <h3>修改密码</h3>
          <input
            type="password"
            placeholder="当前密码"
            value={oldPassword}
            autoComplete="current-password"
            onChange={(e) => setOldPassword(e.target.value)}
          />
          <input
            type="password"
            placeholder="新密码（至少 6 位）"
            value={newPassword}
            autoComplete="new-password"
            onChange={(e) => setNewPassword(e.target.value)}
          />
          <input
            type="password"
            placeholder="确认新密码"
            value={confirm}
            autoComplete="new-password"
            onChange={(e) => setConfirm(e.target.value)}
          />
          <button type="submit" className="admin-btn" disabled={busy || !oldPassword || !newPassword || !confirm}>
            {busy ? '提交中…' : '修改密码'}
          </button>
          <p className="admin-sub">修改成功后旧密码立即失效；管理端登录态会自动换成新 token。</p>
        </form>

        <footer className="admin-profile-foot">
          <button
            type="button"
            className="admin-btn ghost"
            onClick={() => {
              // 先记账再清本地 token（登出也是一条审计）
              void adminLogout().finally(() => {
                adminClearToken();
                onLogout();
              });
            }}
          >
            退出管理端
          </button>
        </footer>
      </div>
    </div>
  );
}
