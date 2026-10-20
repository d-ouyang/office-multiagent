// 登录页（p6.1）：username + password → /api/v1/auth/login → token 入 localStorage。
import { useState } from 'react';

import { login } from '../lib/api';

export function LoginPage({ onLoggedin }: { onLoggedin: () => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
      onLoggedin();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page login-page">
      <header>
        <h1>office-multiagent</h1>
        <p>智能办公助手 · 请登录</p>
      </header>
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
          {busy ? '登录中…' : '登录'}
        </button>
      </form>
    </div>
  );
}

export default LoginPage;
