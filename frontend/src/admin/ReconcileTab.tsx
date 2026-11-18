// 任务对账（v2.4.3）：预扣 / 真实用量 / 折扣后结算 三列对齐。
// 自洽公式：settle == actual − cache_read + ceil(cache_read × cache 折扣比例)；
// 不符即缓存折扣或结算逻辑有 bug（标红）。预扣 < 实际一半时提示"预估偏低"。
import { useCallback, useEffect, useState } from 'react';

import { adminReconcile, type ReconcileRow } from '../lib/api';
import { AdminListPage } from './AdminListPage';
import { humanizeAdminError } from './errors';
import { fmtShanghai } from './format';
import { Alert, Table, Tag } from './ui';

export default function ReconcileTab() {
  const [rows, setRows] = useState<ReconcileRow[]>([]);
  const [ratio, setRatio] = useState(0.25);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await adminReconcile({ days: 7, limit: 200 });
      setRows(data.rows);
      setRatio(data.ratio);
      setError('');
    } catch (e) {
      setError(humanizeAdminError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const bad = rows.filter((r) => !r.ok).length;
  const under = rows.filter((r) => r.under_reserved).length;

  return (
    <AdminListPage
      extra={`最近 7 天 · ${rows.length} 条 · 自洽公式 settle = actual − cache + ceil(cache × ${ratio}) · 点击右上刷新重拉`}
    >
      {error && <Alert type="error" message={error} />}
      {rows.length > 0 && (
        <>
          {bad > 0 && (
            <Alert
              type="error"
              showIcon
              message={`${bad} 条对账不符（settle ≠ 应扣），请排查结算逻辑`}
              style={{ marginBottom: 8 }}
            />
          )}
          {under > 0 && (
            <Alert
              type="warning"
              showIcon
              message={`${under} 条预扣低于实际一半（预估偏低），钱包会被事后补扣`}
              style={{ marginBottom: 8 }}
            />
          )}
        </>
      )}
      <Table
        size="small"
        rowKey={(r) => `${r.task_id}-${r.created_at}`}
        loading={loading}
        dataSource={rows}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        columns={[
          { title: '时间', dataIndex: 'created_at', width: 150, render: (v: string) => fmtShanghai(v) },
          { title: '用户', dataIndex: 'username', width: 100 },
          { title: '任务', dataIndex: 'task_id', width: 110, render: (v: string) => v?.slice(0, 10) },
          { title: '模型', dataIndex: 'model', width: 150, ellipsis: true },
          { title: '预扣', dataIndex: 'reserve', width: 90, align: 'right' },
          {
            title: '实际消耗',
            dataIndex: 'actual',
            width: 110,
            align: 'right',
            render: (v: number, r: ReconcileRow) => (
              <span>
                {v.toLocaleString()}
                {r.under_reserved && (
                  <Tag color="orange" style={{ marginLeft: 4 }}>
                    预估偏低
                  </Tag>
                )}
              </span>
            ),
          },
          { title: '缓存命中', dataIndex: 'cache_read', width: 100, align: 'right' },
          { title: '应扣', dataIndex: 'expected', width: 100, align: 'right' },
          {
            title: '结算',
            dataIndex: 'settle',
            width: 100,
            align: 'right',
            render: (v: number, r: ReconcileRow) =>
              r.ok ? <span>{v.toLocaleString()}</span> : <Tag color="red">{v.toLocaleString()}</Tag>,
          },
          {
            title: '对账',
            dataIndex: 'ok',
            width: 80,
            render: (v: boolean) =>
              v ? <Tag color="green">✓</Tag> : <Tag color="red">✗ 不符</Tag>,
          },
        ]}
      />
    </AdminListPage>
  );
}
