// 管理端独立登录页（p6.27）：与工作台登录同一账号体系，但独立 token + 角色校验。
import { useState } from 'react';

import { adminLogin, type LoginUser } from '../lib/api';

function goWorkspace() {
  window.history.pushState({}, '', '/');
  window.dispatchEvent(new PopStateEvent('popstate'));
}

export default function AdminLoginPage({ onLoggedin }: { onLoggedin: (u: LoginUser) => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      onLoggedin(await adminLogin(username.trim(), password));
    } catch (err) {
      setError((err as Error).message || '登录失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page login-page admin-login">
      <div className="login-card">
        <div className="admin-login-brand">
          <span className="admin-login-badge">ADMIN</span>
          <h1>管理端</h1>
        </div>
        <p className="sub">office-multiagent · 仅管理员账号可登录</p>
        <form className="login-form" method="post" action="/api/v1/auth/login" onSubmit={submit}>
          <input
            name="username"
            placeholder="管理员账号"
            value={username}
            autoFocus
            autoComplete="username"
            onChange={(e) => setUsername(e.target.value)}
          />
          <input
            name="password"
            type="password"
            placeholder="密码"
            value={password}
            autoComplete="current-password"
            onChange={(e) => setPassword(e.target.value)}
          />
          {error && <p className="login-error" role="alert">{error}</p>}
          <button type="submit" disabled={busy || !username.trim() || !password}>
            {busy ? '登录中…' : '登录管理端'}
          </button>
        </form>
        <button type="button" className="admin-login-back" onClick={goWorkspace}>
          ← 返回工作台
        </button>
      </div>
    </div>
  );
}
