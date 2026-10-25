import { useEffect, useMemo, useState } from 'react';

import { adminOverview, adminUsage, getHealth, type AdminOverview, type UsagePoint } from '../lib/api';
import { humanizeAdminError } from './errors';
import { fmtTokens } from './format';
import { goAdmin, type AdminTab } from './nav';
import { Alert, Button, Card, Col, Row, Segmented, Space, Statistic, Tag, Typography } from './ui';

function KpiCard({
  title,
  value,
  hint,
  warn,
  onClick,
}: {
  title: string;
  value: string | number;
  hint?: string;
  warn?: boolean;
  onClick?: () => void;
}) {
  return (
    <Card
      size="small"
      hoverable={!!onClick}
      className={`admin-kpi ${onClick ? 'clickable' : ''} ${warn ? 'warn' : ''}`}
      onClick={onClick}
    >
      <Statistic title={title} value={value} />
      {hint && <Typography.Text type="secondary">{hint}</Typography.Text>}
    </Card>
  );
}

const SHORTCUTS: Array<{ tab: AdminTab; title: string; hint: string }> = [
  { tab: 'tasks', title: '任务监控', hint: '全局任务与问答溯源' },
  { tab: 'users', title: '用户额度', hint: '精确搜索、充值、流水' },
  { tab: 'pools', title: '模型池', hint: '角色可见模型与参数' },
  { tab: 'audit', title: '审计日志', hint: '只读操作痕迹' },
];

export default function OverviewTab() {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [health, setHealth] = useState<{ status: string; services?: Record<string, { ok: boolean; detail?: string | null }> } | null>(null);
  const [series, setSeries] = useState<UsagePoint[]>([]);
  const [days, setDays] = useState(7);
  const [error, setError] = useState('');

  useEffect(() => {
    adminOverview().then(setOverview).catch((e) => setError(humanizeAdminError(e, '加载概览失败，请稍后重试')));
    getHealth().then(setHealth).catch(() => setHealth({ status: 'error' }));
  }, []);

  useEffect(() => {
    adminUsage(days).then((u) => setSeries(u.series)).catch(() => setSeries([]));
  }, [days]);

  const max = useMemo(() => Math.max(1, ...series.map((p) => p.tokens)), [series]);
  const services = health?.services ?? {};

  return (
    <Space direction="vertical" size={20} style={{ width: '100%' }} className="admin-page-pad">
      {error && <Alert type="error" showIcon message={error} />}
      <Typography.Text type="secondary">
        <Tag color={health?.status === 'ok' ? 'success' : health ? 'error' : 'default'}>
          {health?.status === 'ok' ? '服务正常' : health ? '服务异常' : '正在查看服务'}
        </Tag>
      </Typography.Text>

      {overview && (
        <Row gutter={[12, 12]}>
          <Col xs={12} md={8} xl={4}>
            <KpiCard
              title="暂停中"
              value={overview.tasks_paused}
              warn={overview.tasks_paused > 0}
              onClick={() => goAdmin('tasks', { flag: 'paused' })}
            />
          </Col>
          <Col xs={12} md={8} xl={4}>
            <KpiCard
              title="近 7 日失败"
              value={overview.tasks_failed_7d ?? 0}
              onClick={() => goAdmin('tasks', { status: 'paused_error' })}
            />
          </Col>
          <Col xs={12} md={8} xl={4}>
            <KpiCard
              title="完成率"
              value={overview.completion_rate == null ? '—' : `${Math.round(overview.completion_rate * 100)}%`}
              onClick={() => goAdmin('tasks')}
            />
          </Col>
          <Col xs={12} md={8} xl={4}>
            <KpiCard title="今日任务" value={overview.tasks_today} onClick={() => goAdmin('tasks')} />
          </Col>
          <Col xs={12} md={8} xl={4}>
            <KpiCard title="用户数" value={overview.users_total} onClick={() => goAdmin('users')} />
          </Col>
          <Col xs={12} md={8} xl={4}>
            <KpiCard
              title="本月消耗"
              value={fmtTokens(overview.month_tokens)}
              hint={`${overview.month_calls} 次任务`}
              onClick={() => goAdmin('tasks')}
            />
          </Col>
        </Row>
      )}

      <Card title="系统状态">
        <Row gutter={[12, 12]}>
          <Col xs={12} md={6}>
            <KpiCard
              title="整体"
              value={health?.status === 'ok' ? '正常' : health ? '异常' : '…'}
              warn={health?.status !== 'ok'}
            />
          </Col>
          {Object.entries(services).map(([name, s]) => (
            <Col xs={12} md={6} key={name}>
              <KpiCard title={name} value={s.ok ? '正常' : '异常'} hint={s.detail ?? undefined} warn={!s.ok} />
            </Col>
          ))}
        </Row>
      </Card>

      <Card
        title={`用量概览 · 近 ${days} 天`}
        extra={(
          <Segmented
            size="large"
            value={days}
            onChange={(v) => setDays(Number(v))}
            options={[7, 14, 30].map((d) => ({ label: `${d} 天`, value: d }))}
          />
        )}
      >
        {overview && (
          <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
            <Col xs={12} md={6}>
              <KpiCard title="余额合计" value={fmtTokens(overview.balance_total)} onClick={() => goAdmin('users')} />
            </Col>
            <Col xs={12} md={6}>
              <KpiCard
                title="累计充值"
                value={fmtTokens(overview.recharge_total)}
                hint={`${overview.recharge_count} 笔`}
                onClick={() => goAdmin('users')}
              />
            </Col>
            <Col xs={12} md={6}>
              <KpiCard title="任务总数" value={overview.tasks_total} onClick={() => goAdmin('tasks')} />
            </Col>
            <Col xs={12} md={6}>
              <KpiCard
                title="数字未对齐"
                value={overview.validation_mismatches ?? 0}
                onClick={() => goAdmin('tasks', { flag: 'validation' })}
              />
            </Col>
          </Row>
        )}
        {series.length === 0 && <Typography.Text type="secondary">这段时间还没有消耗记录。</Typography.Text>}
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
      </Card>

      <Card title="快捷入口">
        <Space wrap size={12}>
          {SHORTCUTS.map((item) => (
            <Button key={item.tab} type="default" size="large" onClick={() => goAdmin(item.tab)}>
              <span>
                <strong>{item.title}</strong>
                <Typography.Text type="secondary" style={{ marginLeft: 8 }}>{item.hint}</Typography.Text>
              </span>
            </Button>
          ))}
        </Space>
      </Card>
    </Space>
  );
}
