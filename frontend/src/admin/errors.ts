/** 把接口/解析异常收成中文 Alert，绝不把 Unexpected token 甩到页面上。 */
export function isUglyAdminError(raw: string): boolean {
  return /Unexpected token|is not valid JSON|JSON\.parse|Failed to fetch|NetworkError|LOAD_FAILED|BAD_JSON|^HTTP \d+$|SyntaxError/i.test(raw)
    || raw.length > 120
    || /[{[]/.test(raw);
}

export function humanizeAdminError(error: unknown, fallback = '加载失败，请稍后重试'): string {
  const raw = error instanceof Error ? error.message : String(error ?? '');
  if (raw === 'FORBIDDEN') return '需要管理员权限';
  if (raw === 'UNAUTHORIZED') return '登录已失效，请重新登录';
  if (!raw || isUglyAdminError(raw)) return fallback;
  return raw;
}
