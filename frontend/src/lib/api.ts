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
  /** p7.1：task=任务账 / recharge=充值 */
  kind?: string | null;
  note?: string | null;
  /** p6.26：充值金额（任务账为 null） */
  amount?: number | null;
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

// --------------------------------------------------------------------------- //
// p7.1：暂停 / 续跑
// --------------------------------------------------------------------------- //

export interface PausedTask {
  id: string;
  session_id: string;
  status: string;
  text: string;
  pause_reason?: string | null;
  pause_payload?: Record<string, unknown> | null;
  created_at?: string;
}

/** 请求暂停运行中的任务（按 run_id） */
export async function pauseTask(runId: string): Promise<boolean> {
  const res = await fetch(`/api/v1/tasks/${encodeURIComponent(runId)}/pause`, {
    method: 'POST',
    headers: authHeaders(),
  });
  return res.ok;
}

/** 我的任务列表（可按状态/会话过滤） */
export async function listTasks(params: { status?: string; session_id?: string; limit?: number } = {}): Promise<PausedTask[]> {
  const qs = new URLSearchParams();
  if (params.status) qs.set('status', params.status);
  if (params.session_id) qs.set('session_id', params.session_id);
  qs.set('limit', String(params.limit ?? 20));
  const res = await fetch(`/api/v1/tasks?${qs.toString()}`, { headers: authHeaders() });
  if (res.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  const data = await res.json();
  return data.tasks ?? [];
}

/** 某会话最近一条"暂停/失败"任务（刷新后横幅还能出现） */
export async function latestPausedTask(sessionId: string): Promise<PausedTask | null> {
  const tasks = await listTasks({ session_id: sessionId, limit: 10 });
  return tasks.find((t) => String(t.status).startsWith('paused') || t.status === 'failed') ?? null;
}

/** 续跑/重试：返回原始 Response 供 consumeNdjson 消费 */
export async function resumeTaskResponse(taskId: string): Promise<Response> {
  return fetch(`/api/v1/tasks/${encodeURIComponent(taskId)}/resume`, {
    method: 'POST',
    headers: { Accept: 'application/x-ndjson', ...authHeaders() },
  });
}

// --------------------------------------------------------------------------- //
// p7.1：管理端（充值 + 用户列表）
// --------------------------------------------------------------------------- //

export interface AdminUser {
  id: number;
  employee_id: string;
  username: string;
  role: string;
  model_pool_id?: number | null;
  balance: number;
}

export async function adminListUsers(q?: string): Promise<AdminUser[]> {
  const qs = new URLSearchParams();
  if (q?.trim()) qs.set('q', q.trim());
  const res = await fetch(`/api/v1/admin/users?${qs.toString()}`, { headers: authHeaders() });
  if (res.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  if (res.status === 403) throw new Error('FORBIDDEN');
  const data = await res.json();
  return data.users ?? [];
}

export async function adminRecharge(userId: number, amount: number, note?: string): Promise<number> {
  const res = await fetch(`/api/v1/admin/users/${userId}/recharge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ amount, note: note || null }),
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  if (!res.ok) {
    throw new Error(String(data?.detail?.message ?? data?.message ?? `充值失败（HTTP ${res.status}）`));
  }
  return Number(data.balance);
}

export async function adminUserLedger(userId: number, limit = 20): Promise<LedgerEntry[]> {
  const res = await fetch(`/api/v1/admin/users/${userId}/ledger?limit=${limit}`, {
    headers: authHeaders(),
  });
  if (!res.ok) return [];
  const data = await res.json();
  return data.ledger ?? [];
}

// --------------------------------------------------------------------------- //
// p6.26：管理端概览 / 用量 / 任务监控 / 系统状态
// --------------------------------------------------------------------------- //

export interface AdminOverview {
  users_total: number;
  balance_total: number;
  tasks_total: number;
  tasks_today: number;
  tasks_paused: number;
  month_tokens: number;
  month_calls: number;
  recharge_total: number;
  recharge_count: number;
}

export interface UsagePoint {
  date: string;
  tokens: number;
  calls: number;
}

export interface AdminTaskRow {
  id: string;
  user_id: number | null;
  username: string | null;
  status: string;
  pause_reason: string | null;
  text: string;
  tokens_used: number;
  created_at: string | null;
}

async function adminGet<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: authHeaders() });
  if (res.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  if (res.status === 403) throw new Error('FORBIDDEN');
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as T;
}

export function adminOverview(): Promise<AdminOverview> {
  return adminGet<AdminOverview>('/api/v1/admin/overview');
}

export function adminUsage(days = 7): Promise<{ days: number; series: UsagePoint[] }> {
  return adminGet(`/api/v1/admin/usage?days=${days}`);
}

export async function adminTasks(status?: string, limit = 30): Promise<AdminTaskRow[]> {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (status) qs.set('status', status);
  const data = await adminGet<{ tasks: AdminTaskRow[] }>(`/api/v1/admin/tasks?${qs.toString()}`);
  return data.tasks ?? [];
}

/** 系统状态（公开接口，不需要 token 也能看；这里带上 token 无害） */
export async function getHealth(): Promise<{
  status: string;
  services?: Record<string, { ok: boolean; detail?: string | null }>;
}> {
  const res = await fetch('/api/v1/health');
  return res.json();
}
