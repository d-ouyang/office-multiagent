// 登录态管理（p6.1）：token 存取 + 登录请求 + 401 统一处理。
const TOKEN_KEY = 'office_token';

export interface LoginUser {
  employee_id: string;
  username: string;
  role: string;
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

/** 登录：成功存 token 并返回用户；失败抛 Error(message)。 */
export async function login(username: string, password: string): Promise<LoginUser> {
  const res = await fetch('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(String(data?.error?.message ?? `登录失败（HTTP ${res.status}）`));
  }
  setToken(String(data.access_token));
  return data.user as LoginUser;
}

export function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

/** 登录态检查（/auth/me）：有效返回用户，无效/未登录清 token 返回 null。 */
export async function checkSession(): Promise<LoginUser | null> {
  const t = getToken();
  if (!t) return null;
  try {
    const res = await fetch('/api/v1/auth/me', { headers: authHeaders() });
    if (!res.ok) {
      if (res.status === 401) clearToken();
      return null;
    }
    return (await res.json()) as LoginUser;
  } catch {
    return null;
  }
}
