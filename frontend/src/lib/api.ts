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

/** p6.2c：我的会话列表（title=首条用户消息前 20 字）。 */
export async function listSessions(): Promise<Array<{ session_id: string; title: string; created_at: string }>> {
  const res = await fetch('/api/v1/sessions', { headers: authHeaders() });
  if (res.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  const data = await res.json();
  return data.sessions ?? [];
}

/** p6.2c：建会话（可选默认模型）。 */
export async function createSession(model?: string): Promise<string> {
  const res = await fetch('/api/v1/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ model: model ?? null }),
  });
  if (res.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  const data = await res.json();
  return String(data.session_id);
}

/** p6.2c：会话历史消息（user/assistant 终答）。 */
export async function getMessages(sessionId: string): Promise<Array<{ role: string; content: string; created_at: string }>> {
  const res = await fetch(`/api/v1/sessions/${encodeURIComponent(sessionId)}/messages`, {
    headers: authHeaders(),
  });
  if (res.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  const data = await res.json();
  return data.messages ?? [];
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
