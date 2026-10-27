export type AdminTab = 'overview' | 'tasks' | 'users' | 'pools' | 'audit' | 'feedback';

export const ADMIN_TABS: Array<{ key: AdminTab; label: string; hint: string; icon: string }> = [
  { key: 'overview', label: '概览', hint: '指标、系统状态和用量', icon: '▣' },
  { key: 'tasks', label: '任务监控', hint: '全局任务与问答溯源', icon: '◎' },
  { key: 'users', label: '用户额度', hint: '员工余额、充值与流水', icon: '◈' },
  { key: 'pools', label: '模型池', hint: '角色可见模型与参数', icon: '⬡' },
  { key: 'audit', label: '审计日志', hint: '谁在什么时候做了什么', icon: '▤' },
  { key: 'feedback', label: '意见反馈', hint: '回答的点赞点踩与原因', icon: '♡' },
];

const LEGACY: Record<string, AdminTab> = {
  usage: 'overview',
  system: 'overview',
  runs: 'tasks',
};

export function readAdminTab(hash = typeof window === 'undefined' ? '' : window.location.hash): AdminTab {
  const key = hash.replace('#', '');
  if (LEGACY[key]) return LEGACY[key];
  return ADMIN_TABS.some((t) => t.key === key) ? (key as AdminTab) : 'overview';
}

export function goAdmin(tab: AdminTab, query: Record<string, string> = {}) {
  const qs = new URLSearchParams(query).toString();
  window.history.replaceState({}, '', `/admin${qs ? `?${qs}` : ''}#${tab}`);
  window.dispatchEvent(new HashChangeEvent('hashchange'));
}
