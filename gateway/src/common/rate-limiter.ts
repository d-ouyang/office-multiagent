/**
 * 固定窗口限流计数器（p5.0 Phase C）——纯逻辑，可单测。
 * 每 key（IP）一个窗口计数；窗口过期重置。带 key 数上限，超限整表清空（限流是尽力而为，
 * 防无限 IP 打爆内存）。多副本下为每实例计数，严格全局限流需共享存储（Redis），文档标注。
 */
export class FixedWindowCounter {
  private readonly hits = new Map<string, { count: number; resetAt: number }>();

  constructor(
    private readonly max: number,
    private readonly windowMs: number,
    private readonly maxKeys = 10_000,
  ) {}

  /** 返回 true=放行，false=超限。 */
  allow(key: string, now: number): boolean {
    if (this.max <= 0) return true; // 0=关闭
    if (this.hits.size >= this.maxKeys) this.hits.clear();
    const cur = this.hits.get(key);
    if (!cur || now >= cur.resetAt) {
      this.hits.set(key, { count: 1, resetAt: now + this.windowMs });
      return true;
    }
    cur.count += 1;
    return cur.count <= this.max;
  }
}
