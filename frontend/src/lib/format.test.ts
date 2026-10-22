import { describe, expect, it } from 'vitest';

import { formatClock, formatDuration, formatLedgerTime, formatTokens } from './format';

describe('formatClock', () => {
  it('显示本地 HH:MM', () => {
    const ts = new Date(2026, 9, 21, 22, 1, 0).getTime();
    expect(formatClock(ts)).toBe('22:01');
  });
  it('非法时间返回空串', () => {
    expect(formatClock(undefined)).toBe('');
    expect(formatClock(0)).toBe('');
  });
});

describe('formatDuration', () => {
  it('按量级显示', () => {
    expect(formatDuration(800)).toBe('800ms');
    expect(formatDuration(3200)).toBe('3.2s');
    expect(formatDuration(12500)).toBe('13s');
    expect(formatDuration(65000)).toBe('1分5秒');
  });
  it('缺失显示破折号', () => {
    expect(formatDuration(undefined)).toBe('—');
  });
});

describe('formatLedgerTime', () => {
  it('无时区的 UTC 字符串按本地时间显示', () => {
    const local = new Date(2026, 9, 22, 10, 45);
    const naive = new Date(local.getTime()).toISOString().slice(0, 19).replace('T', ' ');
    expect(formatLedgerTime(naive)).toBe('10月22日 10:45');
  });
  it('空值显示破折号', () => {
    expect(formatLedgerTime(undefined)).toBe('—');
    expect(formatLedgerTime('')).toBe('—');
  });
});

describe('formatTokens', () => {
  it('千分位', () => {
    expect(formatTokens(3011)).toBe('3,011');
  });
  it('缺失不是 0', () => {
    expect(formatTokens(undefined)).toBe('—');
  });
});
