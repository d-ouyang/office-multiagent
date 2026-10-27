// 管理端「意见反馈」（v2.0.0-p2.3，PLAN-2.0.0 §4.5）：统计卡 + 筛选（评分/原因/关键词）+ 只读明细分页。
// 只读纪律：不提供删除/修改（与审计一致）；会话 id 可复制跳任务监控排查。
import { useCallback, useEffect, useState } from 'react';

import { adminFeedback, FEEDBACK_TAGS, type AdminFeedbackItem, type AdminFeedbackStats } from '../lib/api';
import { AdminListPage, AdminPager, PAGE_SIZE } from './AdminListPage';
import { CopyCell } from './ellipsis';
import { humanizeAdminError } from './errors';
import { fmtShanghai } from './format';
import { Alert, Card, Col, Empty, Input, Row, Select, Space, Statistic, Table, Tag, Typography } from './ui';
import { useDebouncedValue } from './useDebouncedValue';

const RATING_OPTIONS = [
  { value: '', label: '全部评分' },
  { value: 'like', label: '👍 点赞' },
  { value: 'dislike', label: '👎 点踩' },
];

const TAG_OPTIONS = [{ value: '', label: '全部原因' }, ...FEEDBACK_TAGS.map((t) => ({ value: t, label: t }))];

function ratingTag(rating: string) {
  return rating === 'like' ? <Tag color="green">👍 点赞</Tag> : <Tag color="red">👎 点踩</Tag>;
}

export default function FeedbackTab() {
  const [rows, setRows] = useState<AdminFeedbackItem[]>([]);
  const [stats, setStats] = useState<AdminFeedbackStats | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [rating, setRating] = useState('');
  const [tag, setTag] = useState('');
  const [kw, setKw] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const debouncedKw = useDebouncedValue(kw, 300);

  const load = useCallback(
    async (pg = page) => {
      setLoading(true);
      try {
        const data = await adminFeedback({
          rating: rating || undefined,
          tag: tag || undefined,
          q: debouncedKw || undefined,
          page: pg,
          pageSize: PAGE_SIZE,
        });
        setRows(data.items);
        setStats(data.stats);
        setTotal(data.total);
        setError('');
      } catch (e) {
        setError(humanizeAdminError(e));
      } finally {
        setLoading(false);
      }
    },
    [page, rating, tag, debouncedKw],
  );

  useEffect(() => {
    void load(1);
    setPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rating, tag, debouncedKw]);

  return (
    <div>
      {stats && (
        <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
          <Col flex="1"><Card size="small"><Statistic title="总反馈" value={stats.total} /></Card></Col>
          <Col flex="1"><Card size="small"><Statistic title="点赞" value={stats.like} /></Card></Col>
          <Col flex="1"><Card size="small"><Statistic title="点踩" value={stats.dislike} /></Card></Col>
          <Col flex="1">
            <Card size="small">
              <Statistic title="点踩率" value={stats.dislike_rate == null ? '—' : `${(stats.dislike_rate * 100).toFixed(1)}%`} />
            </Card>
          </Col>
          <Col flex="2">
            <Card size="small">
              <Typography.Text type="secondary">Top 原因</Typography.Text>
              <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {stats.top_tags.length === 0
                  ? <Typography.Text type="secondary">暂无</Typography.Text>
                  : stats.top_tags.map(([t, n]) => (
                    <Tag key={t} onClick={() => setTag(t === tag ? '' : t)} style={{ cursor: 'pointer' }}>
                      {t} × {n}
                    </Tag>
                  ))}
              </div>
            </Card>
          </Col>
        </Row>
      )}

      <Space wrap style={{ marginBottom: 12 }}>
        <Select value={rating} options={RATING_OPTIONS} onChange={(v) => setRating(String(v))} style={{ width: 130 }} />
        <Select value={tag} options={TAG_OPTIONS} onChange={(v) => setTag(String(v))} style={{ width: 190 }} />
        <Input.Search
          allowClear
          placeholder="按反馈说明 / 回答内容搜索"
          value={kw}
          onChange={(e) => setKw(e.target.value)}
          style={{ width: 260 }}
        />
      </Space>

      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}

      <Table
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={rows}
        locale={{ emptyText: <Empty description="还没有反馈" /> }}
        pagination={false}
        columns={[
          { title: '时间', width: 170, render: (_, r) => fmtShanghai(r.created_at) },
          { title: '用户', width: 90, render: (_, r) => r.username ?? '—' },
          { title: '工号', width: 100, render: (_, r) => r.employee_id ?? '—' },
          { title: '评分', width: 96, render: (_, r) => ratingTag(r.rating) },
          {
            title: '原因',
            render: (_, r) => (
              <Space size={4} wrap>
                {r.tags.map((t) => <Tag key={t}>{t}</Tag>)}
                {r.comment && <Typography.Text type="secondary">「{r.comment}」</Typography.Text>}
              </Space>
            ),
          },
          {
            title: '回答摘要',
            width: 260,
            ellipsis: true,
            render: (_, r) => <Typography.Text type="secondary">{r.message_snippet || '—'}</Typography.Text>,
          },
          {
            title: '会话',
            width: 200,
            render: (_, r) => <CopyCell text={r.session_id} width={200} />,
          },
        ]}
      />
      <AdminPager page={page} pageSize={PAGE_SIZE} total={total} onChange={(p) => { setPage(p); void load(p); }} />
    </div>
  );
}
