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

/** p6.2c：我的会话列表（title=首条用户消息前 20 字；p6.12 起 updated_at=最后一次问答时间）。 */
export async function listSessions(): Promise<Array<{ session_id: string; title: string; pinned?: boolean; created_at: string; updated_at: string }>> {
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

export async function updateSession(
  sessionId: string,
  body: { title?: string; pinned?: boolean; model?: string },
): Promise<void> {
  const res = await fetch(`/api/v1/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (res.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  if (!res.ok) throw new Error('更新会话失败');
}

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`/api/v1/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (res.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  if (!res.ok) throw new Error('删除会话失败');
}

/** p6.2c/p6.7：会话历史消息（user/assistant 终答 + assistant 的 trace 过程事件 JSON）。 */
export async function getMessages(sessionId: string): Promise<Array<{
  role: string;
  content: string;
  trace?: string | null;
  created_at: string;
  model?: string | null;
  tokens?: number | null;
}>> {
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

/** 改密。成功后换成新 token（旧 token 的 token_version 已失效）。 */
export async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  const res = await fetch('/api/v1/auth/password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(String(data?.message ?? data?.error?.message ?? `修改失败（HTTP ${res.status}）`));
  }
  if (data.access_token) setToken(String(data.access_token));
}

export interface LedgerEntry {
  task_id?: string | null;
  model?: string | null;
  reserve?: number | null;
  settle?: number | null;
  created_at?: string;
}

/** p6.4：我的 token 余额与流水。 */
export async function getQuota(): Promise<{
  balance: number;
  ledger: LedgerEntry[];
  usage?: { month_tokens: number; month_count: number; total_tokens: number; total_count: number };
}> {
  const res = await fetch('/api/v1/quota', { headers: authHeaders() });
  if (res.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  return res.json();
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
