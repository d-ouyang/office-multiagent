import { FixedWindowCounter } from './rate-limiter';

describe('FixedWindowCounter', () => {
  it('窗口内计数、超限拒绝、过期重置', () => {
    const c = new FixedWindowCounter(3, 1000);
    const t0 = 1_000_000;
    expect(c.allow('ip', t0)).toBe(true);
    expect(c.allow('ip', t0 + 1)).toBe(true);
    expect(c.allow('ip', t0 + 2)).toBe(true);
    expect(c.allow('ip', t0 + 3)).toBe(false); // 第 4 次超限
    expect(c.allow('ip', t0 + 1000)).toBe(true); // 窗口过，重置
  });

  it('不同 key 互不影响', () => {
    const c = new FixedWindowCounter(1, 1000);
    expect(c.allow('a', 1)).toBe(true);
    expect(c.allow('a', 2)).toBe(false);
    expect(c.allow('b', 2)).toBe(true);
  });

  it('max<=0 表示关闭，全放行', () => {
    const c = new FixedWindowCounter(0, 1000);
    for (let i = 0; i < 100; i++) expect(c.allow('ip', i)).toBe(true);
  });

  it('key 数超上限会清表（防内存膨胀，不抛错）', () => {
    const c = new FixedWindowCounter(5, 1000, 3);
    c.allow('a', 1);
    c.allow('b', 1);
    c.allow('c', 1);
    c.allow('d', 1); // 触发清表
    expect(c.allow('a', 1)).toBe(true); // 清表后 a 重新计数
  });
});
