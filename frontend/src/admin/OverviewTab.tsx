import { useEffect, useMemo, useState } from 'react';

import { adminOverview, adminUsage, getHealth, type AdminOverview, type UsagePoint } from '../lib/api';
import { fmtTokens, REASON } from './format';
import { goAdmin } from './nav';

function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: 'warn' }) {
  return (
    <div className={`admin-card ${tone ?? ''}`}>
      <span className="admin-card-label">{label}</span>
      <strong className="admin-card-value">{value}</strong>
      {hint && <span className="admin-card-hint">{hint}</span>}
    </div>
  );
}

export default function OverviewTab() {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [health, setHealth] = useState<{ status: string; services?: Record<string, { ok: boolean; detail?: string | null }> } | null>(null);
  const [series, setSeries] = useState<UsagePoint[]>([]);
  const [days, setDays] = useState(7);
  const [error, setError] = useState('');

  useEffect(() => {
    adminOverview().then(setOverview).catch((e) => setError((e as Error).message));
    getHealth().then(setHealth).catch(() => setHealth({ status: 'error' }));
  }, []);

  useEffect(() => {
    adminUsage(days).then((u) => setSeries(u.series)).catch(() => setSeries([]));
  }, [days]);

  const max = useMemo(() => Math.max(1, ...series.map((p) => p.tokens)), [series]);
  const reasons = overview?.paused_by_reason ?? {};
  const services = health?.services ?? {};

  return (
    <div className="admin-stack">
      {error && <div className="banner err">{error}</div>}

      <p className="admin-health">
        <i className={health?.status === 'ok' ? 'ok' : health ? 'bad' : ''} />
        {health?.status === 'ok' ? '服务正常' : health ? '服务异常' : '正在查看服务'}
      </p>

      {overview && (
        <div className="admin-cards">
          <Stat label="暂停中" value={String(overview.tasks_paused)} tone={overview.tasks_paused > 0 ? 'warn' : undefined} />
          <Stat label="近 7 日失败" value={String(overview.tasks_failed_7d ?? 0)} />
          <Stat label="完成率" value={overview.completion_rate == null ? '—' : `${Math.round(overview.completion_rate * 100)}%`} />
          <Stat label="今日任务" value={String(overview.tasks_today)} />
          <Stat label="用户数" value={String(overview.users_total)} />
          <Stat label="本月消耗" value={fmtTokens(overview.month_tokens)} hint={`${overview.month_calls} 次任务`} />
        </div>
      )}

      <section className="admin-panel">
        <h3>系统状态</h3>
        <div className="admin-cards">
          <Stat
            label="整体"
            value={health?.status === 'ok' ? '正常' : health ? '异常' : '…'}
            tone={health?.status === 'ok' ? undefined : 'warn'}
          />
          {Object.entries(services).map(([name, s]) => (
            <Stat key={name} label={name} value={s.ok ? '正常' : '异常'} hint={s.detail ?? undefined} tone={s.ok ? undefined : 'warn'} />
          ))}
        </div>
      </section>

      <section className="admin-panel">
        <div className="admin-section-head">
          <h3>用量概览 · 近 {days} 天</h3>
          <div className="admin-range">
            {[7, 14, 30].map((d) => (
              <button key={d} type="button" className={`admin-tab ${days === d ? 'active' : ''}`} onClick={() => setDays(d)}>
                {d} 天
              </button>
            ))}
          </div>
        </div>
        {overview && (
          <div className="admin-cards">
            <Stat label="余额合计" value={fmtTokens(overview.balance_total)} />
            <Stat label="累计充值" value={fmtTokens(overview.recharge_total)} hint={`${overview.recharge_count} 笔`} />
            <Stat label="任务总数" value={String(overview.tasks_total)} />
            <Stat label="数字未对齐" value={String(overview.validation_mismatches ?? 0)} />
          </div>
        )}
        {series.length === 0 && <p className="admin-sub">这段时间还没有消耗记录。</p>}
        <div className="admin-bars">
          {series.map((p) => (
            <div className="admin-bar-row" key={p.date}>
              <span className="admin-bar-date">{p.date.slice(5)}</span>
              <span className="admin-bar-track">
                <span className="admin-bar-fill" style={{ width: `${Math.max(2, (p.tokens / max) * 100)}%` }} />
              </span>
              <span className="admin-bar-value">{fmtTokens(p.tokens)}</span>
              <span className="admin-muted">{p.calls} 次</span>
            </div>
          ))}
        </div>
      </section>

      <section className="admin-panel">
        <h3>快捷入口</h3>
        <ul className="admin-todo">
          <li>
            <button type="button" onClick={() => goAdmin('tasks', { flag: 'paused' })}>暂停任务 {overview?.tasks_paused ?? '…'}</button>
            <span>{Object.entries(reasons).map(([k, n]) => `${REASON[k] ?? k} ${n}`).join(' · ') || '暂无暂停'}</span>
          </li>
          <li>
            <button type="button" onClick={() => goAdmin('tasks', { flag: 'validation' })}>数字未对齐</button>
            <span>只观察，不拦截回答</span>
          </li>
          <li>
            <button type="button" onClick={() => goAdmin('users')}>用户额度</button>
            <span>精确搜索、充值、流水</span>
          </li>
          <li>
            <button type="button" onClick={() => goAdmin('pools')}>模型池</button>
            <span>角色可见模型与参数</span>
          </li>
          <li>
            <button type="button" onClick={() => goAdmin('audit')}>审计日志</button>
            <span>只读操作痕迹</span>
          </li>
        </ul>
      </section>
    </div>
  );
}
