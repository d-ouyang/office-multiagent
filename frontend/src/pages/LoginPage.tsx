// 登录页（p6.2 美化）：居中卡片。
import { useState } from 'react';

import { login, type LoginUser } from '../lib/api';

export function LoginPage({ onLoggedin }: { onLoggedin: (u: LoginUser) => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    setBusy(true);
    setError(null);
    try {
      const user = await login(username.trim(), password);
      await rememberPassword(form);
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
        <form className="login-form" method="post" action="/api/v1/auth/login" onSubmit={submit}>
          <label>
            登录名
            <input
              name="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="登录名"
              autoComplete="username"
              autoFocus
            />
          </label>
          <label>
            密码
            <input
              name="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="密码"
              autoComplete="current-password"
            />
          </label>
          {error && <p className="login-error" role="alert">{error}</p>}
          <button type="submit" disabled={busy || !username || !password}>
            {busy ? '登录中…' : '登 录'}
          </button>
        </form>
      </div>
    </div>
  );
}

/** 登录成功后交给浏览器保存。失败的提交不会走到这里，浏览器也不会记错密码。 */
async function rememberPassword(form: HTMLFormElement) {
  const Factory = (window as unknown as { PasswordCredential?: new (form: HTMLFormElement) => Credential }).PasswordCredential;
  if (!Factory || !navigator.credentials?.store) return;
  try {
    await navigator.credentials.store(new Factory(form));
  } catch {
    /* 浏览器拒绝保存时，登录结果不受影响 */
  }
}

export default LoginPage;
