/** 消息时间：本地 HH:MM。 */
export function formatClock(ts: number | undefined): string {
  if (ts == null || !Number.isFinite(ts) || ts <= 0) return '';
  return new Date(ts).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

/** 回复耗时。不足 1 秒用毫秒，1 分钟内用秒，再长用分秒。 */
export function formatDuration(ms: number | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return '—';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const sec = ms / 1000;
  if (sec < 60) return `${sec >= 10 ? Math.round(sec) : sec.toFixed(1)}s`;
  const m = Math.floor(sec / 60);
  const rem = Math.round(sec % 60);
  return `${m}分${rem}秒`;
}

/** 消耗记录时间。库内 UTC，无时区标记时也按 UTC 解析，再显示本地月日时分。 */
export function formatLedgerTime(raw: string | undefined): string {
  if (!raw) return '—';
  const hasZone = /Z$|[+-]\d{2}:\d{2}$/.test(raw);
  const iso = hasZone ? raw : `${raw.replace(' ', 'T')}Z`;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getMonth() + 1}月${d.getDate()}日 ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** token 数。没有数据时用破折号，不用 0 冒充。 */
export function formatTokens(n: number | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—';
  return Math.max(0, Math.round(n)).toLocaleString('zh-CN');
}
