// 登录页（p6.2 美化）：居中卡片。
import { useState } from 'react';

import { login, type LoginUser } from '../lib/api';

export function LoginPage({ onLoggedin }: { onLoggedin: (u: LoginUser) => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const user = await login(username.trim(), password);
      onLoggedin(user);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page login-page">
      <div className="login-card">
        <h1>office-multiagent</h1>
        <p className="sub">智能办公助手 · 请登录</p>
        <form className="login-form" onSubmit={submit}>
          <label>
            登录名
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="username"
              autoComplete="username"
              autoFocus
            />
          </label>
          <label>
            密码
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="password"
              autoComplete="current-password"
            />
          </label>
          {error && <div className="banner err">{error}</div>}
          <button type="submit" disabled={busy || !username || !password}>
            {busy ? '登录中…' : '登 录'}
          </button>
        </form>
      </div>
    </div>
  );
}

export default LoginPage;
