export const STATUS: Record<string, string> = {
  done: '完成',
  resumed: '续跑',
  failed: '出错暂停',
  pending: '排队',
  running: '运行中',
  paused_user: '用户暂停',
  paused_error: '出错暂停',
  paused_insufficient_quota: '配额暂停',
};

export const REASON: Record<string, string> = {
  quota: '配额不足',
  user: '用户主动',
  error: '中途报错',
  input: '待补充',
};

export const KIND: Record<string, string> = {
  reserve: '预扣',
  settle: '结算',
  recharge: '充值',
  task: '任务',
};

const ROLE_LABEL: Record<string, string> = {
  admin: '系统管理员',
  superadmin: '超级管理员',
  staff: '员工',
  user: '成员',
};

export function roleLabel(role: string): string {
  return ROLE_LABEL[role] ?? role;
}

export function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${(n / 10_000).toFixed(1)}w`;
  return n.toLocaleString();
}

export function fmtShanghai(value?: string | null): string {
  if (!value) return '—';
  const raw = value.includes('T') || /[zZ]|[+-]\d{2}:\d{2}$/.test(value)
    ? value
    : value.replace(' ', 'T') + 'Z';
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return value.replace('T', ' ').slice(0, 19);
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date).replace(/\//g, '-');
}

export function fmtDuration(ms?: number | null): string {
  if (ms == null || ms < 0) return '—';
  if (ms < 1000) return `${ms}ms`;
  const sec = Math.round(ms / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  const rem = sec % 60;
  return rem ? `${min}m ${rem}s` : `${min}m`;
}

export function isIncomplete(status: string): boolean {
  return status.startsWith('paused') || status === 'failed' || status === 'running' || status === 'pending';
}

export const TARGET_LABEL: Record<string, string> = {
  auth: '登录态',
  user: '用户',
  task: '任务',
  pool: '模型池',
  model: '模型',
  admin: '管理员',
};

export function renderDetail(action: string, detail: Record<string, unknown> | null): string[] {
  if (!detail) return [];
  const out: string[] = [];
  const push = (k: string, v: unknown) => out.push(`${k} ${v ?? '—'}`);
  if (action === 'admin.recharge') {
    push('充值', `${Number(detail.amount ?? 0).toLocaleString()} tokens`);
    push('充值后余额', Number(detail.balance_after ?? 0).toLocaleString());
    if (detail.note) push('备注', String(detail.note));
  } else if (action === 'admin.user.pool.change') {
    push('新模型池', detail.model_pool_id === null ? '不限制' : `#${detail.model_pool_id}`);
  } else if (action === 'admin.task.resume') {
    push('原任务归属', String(detail.owner_username ?? '—'));
    push('任务内容', String(detail.text ?? '—'));
  } else if (action === 'admin.pool.models.set') {
    const enabled = Array.isArray(detail.enabled) ? detail.enabled : [];
    push('启用模型', `${enabled.length} 个`);
  } else if (action === 'admin.model.update') {
    const fields = Array.isArray(detail.fields) ? detail.fields.join('、') : '—';
    push('改动字段', fields);
  } else if (action === 'admin.password.change') {
    push('结果', '已修改，旧登录态已全部失效');
  } else if (action === 'admin.login.failure') {
    push('原因', detail.reason === 'bad_credentials' ? '用户名或密码错误' : String(detail.reason ?? '—'));
    if (detail.admin === false) push('说明', '账密正确但非管理员角色');
  } else if (action === 'admin.login.success') {
    push('角色', String(detail.role ?? '—'));
  }
  return out;
}
