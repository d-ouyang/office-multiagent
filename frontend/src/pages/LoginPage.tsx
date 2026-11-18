// 登录页（p6.2 美化）：居中卡片。
// 交互补强：密码明文切换（眼睛 icon）、登录成功后交给浏览器保存凭据。
import { useRef, useState } from 'react';

import { login, type LoginUser } from '../lib/api';

export function LoginPage({ onLoggedin }: { onLoggedin: (u: LoginUser) => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const passwordRef = useRef<HTMLInputElement>(null);

  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const account = username.trim();
    setBusy(true);
    setError(null);
    try {
      const user = await login(account, password);
      // 只在登录成功后保存，避免把错误密码写进浏览器的密码管理器。
      await rememberPassword(account, password);
      onLoggedin(user);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  /** 切换明文/密文，并保持输入焦点与光标位置。 */
  const togglePassword = () => {
    setShowPassword((v) => !v);
    const el = passwordRef.current;
    if (!el) return;
    el.focus();
    const end = el.value.length;
    requestAnimationFrame(() => {
      try {
        el.setSelectionRange(end, end);
      } catch {
        /* 个别浏览器对 password 类型不支持选区，忽略即可 */
      }
    });
  };

  return (
    <div className="page login-page">
      <div className="login-card">
        <h1>office-multiagent</h1>
        <p className="sub">智能办公助手 · 请登录</p>
        <form
          id="login-form"
          name="login"
          className="login-form"
          method="post"
          action="/api/v1/auth/login"
          onSubmit={submit}
        >
          <label htmlFor="login-username">
            登录名
            <input
              id="login-username"
              name="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="登录名"
              autoComplete="username"
              autoFocus
            />
          </label>
          <label htmlFor="login-password">
            密码
            <span className="password-field">
              <input
                id="login-password"
                ref={passwordRef}
                name="password"
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="密码"
                autoComplete="current-password"
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
              />
              <button
                type="button"
                className="pwd-toggle"
                onClick={togglePassword}
                onMouseDown={(e) => e.preventDefault()}
                aria-label={showPassword ? '隐藏密码' : '显示密码'}
                aria-pressed={showPassword}
                title={showPassword ? '隐藏密码' : '显示密码'}
              >
                {showPassword ? <EyeOffIcon /> : <EyeIcon />}
              </button>
            </span>
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

function EyeIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12Z" />
      <circle cx="12" cy="12" r="2.8" />
    </svg>
  );
}

function EyeOffIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M9.7 6.3A9.9 9.9 0 0 1 12 6c6 0 9.5 6 9.5 6a16.2 16.2 0 0 1-3.1 3.8" />
      <path d="M6.3 7.9A16 16 0 0 0 2.5 12S6 18 12 18a9.6 9.6 0 0 0 3.2-.5" />
      <path d="M10.2 10.2a2.8 2.8 0 0 0 3.6 3.6" />
      <path d="M3.5 3.5l17 17" />
    </svg>
  );
}

type PasswordCredentialCtor = new (data: { id: string; password: string; name?: string }) => Credential;

/**
 * 登录成功后交给浏览器保存凭据。
 *
 * 这里刻意用「显式凭据对象」而不是 new PasswordCredential(form)：
 * 用 form 构造时浏览器只认 type="password" 的字段，一旦用户开着「显示密码」
 * （此时是 type="text"）提交，读到的凭据就是空的，密码管理器不会弹保存提示。
 * 显式对象与输入框类型无关，也能覆盖 SPA 里 preventDefault 打断原生提交检测的情况。
 */
async function rememberPassword(username: string, password: string) {
  const Ctor = (window as unknown as { PasswordCredential?: PasswordCredentialCtor }).PasswordCredential;
  if (!Ctor || !navigator.credentials?.store) {
    // Safari / Firefox 没有该 API，退回到表单的 autocomplete 启发式：
    // form(method=post) + name + autocomplete=username/current-password 已齐备，
    // 登录成功后表单卸载，浏览器会自行提示保存。
    return;
  }
  try {
    await navigator.credentials.store(new Ctor({ id: username, password, name: username }));
  } catch (err) {
    // 浏览器拒绝保存（无痕模式、站点被设为「永不保存」、非安全上下文等）不影响登录结果。
    console.debug('[login] 浏览器未保存凭据：', err);
  }
}

export default LoginPage;
