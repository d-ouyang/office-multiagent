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
  id?: number;
  role: string;
  content: string;
  trace?: string | null;
  created_at: string;
  model?: string | null;
  tokens?: number | null;
  feedback?: MessageFeedback | null;
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

// --------------------------------------------------------------------------- //
// v2.0.0-p2.2：消息点赞/点踩反馈（闭环：提交/覆盖/取消，DB 为真相源）
// --------------------------------------------------------------------------- //

export type FeedbackRating = 'like' | 'dislike';

export interface MessageFeedback {
  rating: FeedbackRating | null;
  tags: string[];
  comment: string | null;
  at: string | null;
}

/** 原因 tag 白名单——与后端 core/feedback_repo.py 保持一致（8 项）。 */
export const FEEDBACK_TAGS = [
  '误解了我的问题',
  '上下文理解错误',
  '回答模糊、不具体',
  '数据或数字有误',
  '图表或表格有误',
  '工具调用有误',
  '回答不专业',
  '其他原因',
] as const;

export const FEEDBACK_COMMENT_MAX = 200;

async function feedbackError(res: Response): Promise<never> {
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  throw new Error(String(data?.detail?.message ?? `提交失败（HTTP ${res.status}）`));
}

/** 提交/覆盖反馈（点赞可不带原因；点踩须至少 1 tag 或有文字——服务端也校验）。
 *  p2.10：契约守护——回执缺 rating 字段视为失败（p2.8/p2.9 的"图标打回空心"
 *  事故根因就是后端回执字段名 feedback 与前端 rating 不一致，静默解析成 undefined）。 */
export async function submitMessageFeedback(
  sessionId: string,
  messageId: number,
  rating: FeedbackRating,
  tags: string[] = [],
  comment = '',
): Promise<MessageFeedback> {
  const res = await fetch(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/messages/${messageId}/feedback`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ rating, tags, comment }),
    },
  );
  if (!res.ok) await feedbackError(res);
  const data = await res.json();
  const state = data.feedback as MessageFeedback;
  if (!state || (state.rating !== 'like' && state.rating !== 'dislike')) {
    throw new Error('反馈回执格式异常，请刷新页面后重试');
  }
  return state;
}

/** 取消当前反馈（流水保留）。返回是否存在过当前态。 */
export async function cancelMessageFeedback(sessionId: string, messageId: number): Promise<boolean> {
  const res = await fetch(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/messages/${messageId}/feedback`,
    { method: 'DELETE', headers: authHeaders() },
  );
  if (!res.ok) await feedbackError(res);
  const data = await res.json();
  return !!data.cancelled;
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

// --------------------------------------------------------------------------- //
// p6.29：显式长期记忆（用户可查可删）
// --------------------------------------------------------------------------- //

export interface UsageHit {
  task_id?: string | null;
  session_id?: string | null;
  question?: string;
  model?: string | null;
  settle?: number | null;
  created_at?: string;
}

export async function searchUsage(query: {
  model?: string;
  start?: string;
  end?: string;
  minTokens?: string;
  maxTokens?: string;
}): Promise<UsageHit[]> {
  const params = new URLSearchParams();
  if (query.model) params.set('model', query.model);
  if (query.start) params.set('start', query.start);
  if (query.end) params.set('end', query.end);
  if (query.minTokens) params.set('min_tokens', query.minTokens);
  if (query.maxTokens) params.set('max_tokens', query.maxTokens);
  const res = await fetch(`/api/v1/quota/usage?${params}`, { headers: authHeaders() });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  if (!res.ok) {
    throw new Error(String(data?.detail?.message ?? '暂时读不到用量'));
  }
  return data.items ?? [];
}

export interface SettingItem {
  key: string;
  label: string;
  description: string;
  value_type: 'bool' | 'int';
  scope: string;
  value: boolean | number;
  min?: number | null;
  max?: number | null;
}

export async function getSettings(): Promise<{ editable: boolean; items: SettingItem[] }> {
  const res = await fetch('/api/v1/settings', { headers: authHeaders() });
  if (res.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(String(data?.detail?.message ?? '暂时读不到设置'));
  return { editable: !!data.editable, items: data.items ?? [] };
}

export async function saveSetting(key: string, value: boolean | number): Promise<boolean | number> {
  const res = await fetch(`/api/v1/settings/${encodeURIComponent(key)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ value }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(String(data?.detail?.message ?? '保存失败'));
  return data.value;
}

export interface MemoryItem {
  id: number;
  content: string;
  source: string; // agent=助手帮记 / user=手动添加
  created_at: string;
}

export interface MemoryProfile {
  work: string;
  personal: string;
  focus: string;
  history: string;
}

export const EMPTY_PROFILE: MemoryProfile = { work: '', personal: '', focus: '', history: '' };

export async function listMemory(): Promise<MemoryItem[]> {
  const bundle = await getMemoryBundle();
  return bundle.memories;
}

export async function getMemoryBundle(): Promise<{ memories: MemoryItem[]; profile: MemoryProfile }> {
  const res = await fetch('/api/v1/memory', { headers: authHeaders() });
  if (res.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  const data = await res.json();
  return {
    memories: data.memories ?? [],
    profile: { ...EMPTY_PROFILE, ...(data.profile ?? {}) },
  };
}

export async function updateMemory(id: number, content: string): Promise<MemoryItem> {
  const res = await fetch(`/api/v1/memory/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ content }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(String(data?.detail?.message ?? '保存失败'));
  return data as MemoryItem;
}

export async function saveMemoryProfile(profile: MemoryProfile): Promise<MemoryProfile> {
  const res = await fetch('/api/v1/memory/profile', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(profile),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(String(data?.detail?.message ?? '保存失败'));
  return { ...EMPTY_PROFILE, ...(data.profile ?? {}) };
}

export async function addMemory(content: string): Promise<MemoryItem> {
  const res = await fetch('/api/v1/memory', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ content }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(String(data?.detail?.message ?? data?.detail ?? `保存失败（HTTP ${res.status}）`));
  }
  return data as MemoryItem;
}

export async function deleteMemory(id: number): Promise<void> {
  const res = await fetch(`/api/v1/memory/${id}`, { method: 'DELETE', headers: authHeaders() });
  if (res.status === 401) {
    clearToken();
    throw new Error('UNAUTHORIZED');
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(String(data?.detail?.message ?? `删除失败（HTTP ${res.status}）`));
  }
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
// p6.27：管理端独立登录态（独立 token，与工作台互不影响）
// --------------------------------------------------------------------------- //

const ADMIN_TOKEN_KEY = 'office_admin_token';

export function adminGetToken(): string | null {
  return localStorage.getItem(ADMIN_TOKEN_KEY);
}

function adminSetToken(token: string): void {
  localStorage.setItem(ADMIN_TOKEN_KEY, token);
}

export function adminClearToken(): void {
  localStorage.removeItem(ADMIN_TOKEN_KEY);
}

export function adminAuthHeaders(): Record<string, string> {
  const t = adminGetToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

/**
 * 管理端登录（p6.28a）：走后端 /admin/login（账密+角色+审计都在后端）。
 * 与工作台登录（网关 /auth/login）是两条路径，token 分别存放。
 */
export async function adminLogin(username: string, password: string): Promise<LoginUser> {
  const res = await fetch('/api/v1/admin/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(String(data?.detail?.message ?? data?.message ?? `登录失败（HTTP ${res.status}）`));
  }
  const user = data.user as LoginUser;
  if (user.role !== 'admin' && user.role !== 'superadmin') {
    throw new Error('该账号没有管理员权限');
  }
  adminSetToken(String(data.access_token));
  return user;
}

/** 管理端登出（记账；token 无状态，真正失效靠清本地 token）。 */
export async function adminLogout(): Promise<void> {
  try {
    await fetch('/api/v1/admin/logout', { method: 'POST', headers: adminAuthHeaders() });
  } catch {
    /* 登出记账失败不影响本地退出 */
  }
}

export async function adminCheckSession(): Promise<LoginUser | null> {
  if (!adminGetToken()) return null;
  try {
    const res = await fetch('/api/v1/auth/me', { headers: adminAuthHeaders() });
    if (!res.ok) {
      if (res.status === 401) adminClearToken();
      return null;
    }
    const user = (await res.json()) as LoginUser;
    if (user.role !== 'admin' && user.role !== 'superadmin') {
      adminClearToken();
      return null;
    }
    return user;
  } catch {
    return null;
  }
}

/** 管理端个人中心改密（p6.28a）：后端验旧密→改密→踢旧登录态→返回新 admin token。 */
export async function adminChangePassword(oldPassword: string, newPassword: string): Promise<void> {
  const res = await fetch('/api/v1/admin/password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...adminAuthHeaders() },
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(String(data?.detail?.message ?? data?.message ?? `修改失败（HTTP ${res.status}）`));
  }
  if (data.access_token) adminSetToken(String(data.access_token));
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

/** p6.27：管理端代续跑（管理员身份，后端不校验 owner）。 */
export async function adminResumeResponse(taskId: string): Promise<Response> {
  return fetch(`/api/v1/admin/tasks/${encodeURIComponent(taskId)}/resume`, {
    method: 'POST',
    headers: { Accept: 'application/x-ndjson', ...adminAuthHeaders() },
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
  total_used?: number;
}

async function readAdminResponse<T>(res: Response): Promise<T> {
  if (res.status === 401) {
    adminClearToken();
    throw new Error('UNAUTHORIZED');
  }
  if (res.status === 403) throw new Error('FORBIDDEN');
  const text = await res.text();
  let data: Record<string, unknown> = {};
  if (text) {
    try {
      data = JSON.parse(text) as Record<string, unknown>;
    } catch {
      throw new Error(res.ok ? 'BAD_JSON' : 'LOAD_FAILED');
    }
  }
  if (!res.ok) {
    const detail = data.detail as { message?: string } | undefined;
    const msg = detail?.message ?? data.message;
    throw new Error(typeof msg === 'string' && msg ? msg : 'LOAD_FAILED');
  }
  return data as T;
}

export async function adminListUsers(opts: {
  q?: string;
  page?: number;
  pageSize?: number;
  userId?: number;
  role?: string;
} = {}): Promise<{ users: AdminUser[]; total: number; page: number; page_size: number }> {
  const page = opts.page ?? 1;
  const pageSize = opts.pageSize ?? 20;
  const qs = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (opts.q?.trim()) qs.set('q', opts.q.trim());
  if (opts.userId) qs.set('user_id', String(opts.userId));
  if (opts.role?.trim()) qs.set('role', opts.role.trim());
  const res = await fetch(`/api/v1/admin/users?${qs.toString()}`, { headers: adminAuthHeaders() });
  const data = await readAdminResponse<{ users?: AdminUser[]; total?: number; page?: number; page_size?: number }>(res);
  return { users: data.users ?? [], total: data.total ?? 0, page: data.page ?? page, page_size: data.page_size ?? pageSize };
}

export async function adminRecharge(userId: number, amount: number, note?: string): Promise<number> {
  const res = await fetch(`/api/v1/admin/users/${userId}/recharge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...adminAuthHeaders() },
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

export async function adminUserLedger(
  userId: number,
  page = 1,
  pageSize = 20,
): Promise<{ ledger: LedgerEntry[]; total: number; page: number; page_size: number }> {
  const qs = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  const res = await fetch(`/api/v1/admin/users/${userId}/ledger?${qs.toString()}`, {
    headers: adminAuthHeaders(),
  });
  if (!res.ok) return { ledger: [], total: 0, page, page_size: pageSize };
  const data = await res.json();
  return {
    ledger: data.ledger ?? [],
    total: data.total ?? (data.ledger ?? []).length,
    page: data.page ?? page,
    page_size: data.page_size ?? pageSize,
  };
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
  tasks_done?: number;
  tasks_failed_7d?: number;
  paused_by_reason?: Record<string, number>;
  completion_rate?: number | null;
  validation_mismatches?: number;
  avg_tool_steps?: number | null;
}

export interface UsagePoint {
  date: string;
  tokens: number;
  calls: number;
  by_model?: Record<string, number>;
}

export interface AdminTaskRow {
  id: string;
  session_id?: string | null;
  user_id: number | null;
  username: string | null;
  employee_id?: string | null;
  status: string;
  pause_reason: string | null;
  text: string;
  tokens_used: number;
  created_at: string | null;
  duration_ms?: number | null;
  tool_summary?: string;
  rag_called?: boolean;
  validation_mismatch?: boolean;
  identity_mismatch?: boolean;
  has_trace?: boolean;
}

async function adminGet<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: adminAuthHeaders() });
  return readAdminResponse<T>(res);
}

export function adminOverview(): Promise<AdminOverview> {
  return adminGet<AdminOverview>('/api/v1/admin/overview');
}

export function adminUsage(days = 7): Promise<{ days: number; models: string[]; series: UsagePoint[] }> {
  return adminGet(`/api/v1/admin/usage?days=${days}`);
}

export async function adminTasks(
  status?: string,
  page = 1,
  pageSize = 20,
  flag?: string,
  extra: { task_id?: string; session_id?: string; user_id?: number; q?: string; date?: string } = {},
): Promise<{ tasks: AdminTaskRow[]; total: number; page: number; page_size: number }> {
  const qs = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (status) qs.set('status', status);
  if (flag) qs.set('flag', flag);
  if (extra.task_id) qs.set('task_id', extra.task_id);
  if (extra.session_id) qs.set('session_id', extra.session_id);
  if (extra.user_id) qs.set('user_id', String(extra.user_id));
  if (extra.q?.trim()) qs.set('q', extra.q.trim());
  if (extra.date) qs.set('date', extra.date);
  const data = await adminGet<{ tasks: AdminTaskRow[]; total: number; page: number; page_size: number }>(
    `/api/v1/admin/tasks?${qs.toString()}`,
  );
  return { tasks: data.tasks ?? [], total: data.total ?? 0, page: data.page ?? page, page_size: data.page_size ?? pageSize };
}

export interface AdminFlowNode {
  key: string;
  label: string;
  kind: string;
  color?: string;
  terminal?: boolean;
  detail?: string;
}

export interface AdminFlowEdge {
  from: string;
  to: string;
  label?: string;
}

export interface AdminRunFlow {
  question?: string;
  nodes: AdminFlowNode[];
  edges?: AdminFlowEdge[];
  path: string[];
  flow_path?: string[];
  marks?: string[];
  events?: Array<{ type: string; ts?: number; seq?: number; data?: Record<string, unknown> }>;
}

export interface AdminRunDetail extends AdminTaskRow {
  session_id?: string | null;
  tools: string[];
  artifacts: string[];
  validation_note?: string;
  rag_username?: string;
  office_username?: string;
  intents: string[];
  model?: string;
  has_artifact?: boolean;
  flow?: AdminRunFlow;
}

export function adminRun(id: string): Promise<AdminRunDetail> {
  return adminGet<AdminRunDetail>(`/api/v1/admin/runs/${encodeURIComponent(id)}`);
}

// --------------------------------------------------------------------------- //
// p6.28a：审计日志
// --------------------------------------------------------------------------- //

export interface AuditRow {
  id: number;
  actor_user_id: number | null;
  actor_username: string;
  actor_role: string | null;
  action: string;
  action_label: string;
  target_type: string;
  target_id: string | null;
  target_label: string | null;
  detail: Record<string, unknown> | null;
  ip: string | null;
  created_at: string;
}

export async function adminAuditLogs(params: {
  action?: string;
  target_type?: string;
  keyword?: string;
  page?: number;
  page_size?: number;
} = {}): Promise<{ logs: AuditRow[]; total: number; page: number; page_size: number; actions: Array<{ value: string; label: string }>; target_types: string[] }> {
  const qs = new URLSearchParams({ page: String(params.page ?? 1), page_size: String(params.page_size ?? 20) });
  if (params.action) qs.set('action', params.action);
  if (params.target_type) qs.set('target_type', params.target_type);
  if (params.keyword?.trim()) qs.set('keyword', params.keyword.trim());
  const data = await adminGet<{
    logs: AuditRow[]; total: number; page: number; page_size: number;
    actions: Array<{ value: string; label: string }>; target_types: string[];
  }>(`/api/v1/admin/audit-logs?${qs.toString()}`);
  return { ...data, logs: data.logs ?? [], total: data.total ?? 0 };
}

/** 系统状态（公开接口，不需要 token 也能看；这里带上 token 无害） */
export async function getHealth(): Promise<{
  status: string;
  services?: Record<string, { ok: boolean; detail?: string | null }>;
}> {
  const res = await fetch('/api/v1/health');
  return res.json();
}

// --------------------------------------------------------------------------- //
// v2.0.0-p2.3：管理端「意见反馈」（只读）
// --------------------------------------------------------------------------- //

export interface AdminFeedbackItem {
  id: number;
  message_id: number;
  session_id: string;
  user_id: number;
  username: string | null;
  employee_id: string | null;
  rating: FeedbackRating;
  tags: string[];
  comment: string | null;
  message_snippet: string;
  created_at: string | null;
}

export interface AdminFeedbackStats {
  total: number;
  like: number;
  dislike: number;
  dislike_rate: number | null;
  top_tags: Array<[string, number]>;
}

export async function adminFeedback(
  params: { rating?: string; tag?: string; q?: string; page?: number; pageSize?: number } = {},
): Promise<{ stats: AdminFeedbackStats; items: AdminFeedbackItem[]; total: number; page: number; page_size: number }> {
  const qs = new URLSearchParams({ page: String(params.page ?? 1), page_size: String(params.pageSize ?? 20) });
  if (params.rating) qs.set('rating', params.rating);
  if (params.tag) qs.set('tag', params.tag);
  if (params.q?.trim()) qs.set('q', params.q.trim());
  const data = await adminGet<{ stats: AdminFeedbackStats; items?: AdminFeedbackItem[]; total?: number; page?: number; page_size?: number }>(
    `/api/v1/admin/feedback?${qs.toString()}`,
  );
  return {
    stats: data.stats ?? { total: 0, like: 0, dislike: 0, dislike_rate: null, top_tags: [] },
    items: data.items ?? [],
    total: data.total ?? 0,
    page: data.page ?? params.page ?? 1,
    page_size: data.page_size ?? params.pageSize ?? 20,
  };
}

// --------------------------------------------------------------------------- //
// p6.27c：模型池（池定义 / 模型归属 / 用户分配）
// --------------------------------------------------------------------------- //

export interface PoolModelRow {
  model_name: string;
  enabled: boolean;
}

export interface ModelPool {
  id: number;
  name: string;
  user_count: number;
  models: PoolModelRow[];
}

async function adminSend<T>(path: string, method: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json', ...adminAuthHeaders() },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return readAdminResponse<T>(res);
}

export function adminModelPools(): Promise<{ pools: ModelPool[] }> {
  return adminSend<{ pools: ModelPool[] }>('/api/v1/admin/model-pools', 'GET');
}

export function adminCreatePool(name: string): Promise<{ id: number; name: string }> {
  return adminSend<{ id: number; name: string }>('/api/v1/admin/model-pools', 'POST', { name });
}

export function adminSavePoolModels(poolId: number, models: PoolModelRow[]): Promise<{ enabled_count: number }> {
  return adminSend(`/api/v1/admin/model-pools/${poolId}/models`, 'PUT', { models });
}

export function adminDeletePool(poolId: number): Promise<{ ok: boolean }> {
  return adminSend(`/api/v1/admin/model-pools/${poolId}`, 'DELETE');
}

export function adminSetUserPool(userId: number, poolId: number | null): Promise<{ model_pool_id: number | null }> {
  return adminSend(`/api/v1/admin/users/${userId}/pool`, 'PATCH', { model_pool_id: poolId });
}

export interface AdminModel {
  id: string;
  name: string;
  provider: string;
  in_dialogue: boolean;
  enabled?: boolean;
  role?: string | null;
  multimodal_input?: boolean;
  context_window?: number;
  max_output?: number;
  supports_reasoning?: boolean;
  reasoning_efforts?: string[];
  pool_ids?: string[];
  cost_per_1k?: number;
  api_model?: string;
  description?: string;
}

export function adminModelsCatalog(): Promise<{ models: AdminModel[]; providers: Record<string, { base_url?: string }> }> {
  return adminSend('/api/v1/admin/models', 'GET');
}

export function adminUpdateModel(id: string, patch: Partial<AdminModel>): Promise<{ ok: boolean; model: AdminModel }> {
  return adminSend(`/api/v1/admin/models/${encodeURIComponent(id)}`, 'PATCH', patch);
}

export function adminCreateModel(body: Partial<AdminModel> & { id: string; name: string; provider: string; api_model: string }): Promise<{ ok: boolean; model: AdminModel }> {
  return adminSend('/api/v1/admin/models', 'POST', body);
}
