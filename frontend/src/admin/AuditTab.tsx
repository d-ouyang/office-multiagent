import { useCallback, useEffect, useState } from 'react';

import { adminAuditLogs, type AuditRow } from '../lib/api';
import { AdminListPage, AdminPager, PAGE_SIZE } from './AdminListPage';
import { humanizeAdminError } from './errors';
import { fmtShanghai, renderDetail, TARGET_LABEL } from './format';
import { Alert, Button, Empty, Input, Select, Table, Tag } from './ui';
import { useDebouncedValue } from './useDebouncedValue';

export default function AuditTab() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [action, setAction] = useState('');
  const [targetType, setTargetType] = useState('');
  const [keyword, setKeyword] = useState('');
  const debouncedKeyword = useDebouncedValue(keyword, 300);
  const [actions, setActions] = useState<Array<{ value: string; label: string }>>([]);
  const [targetTypes, setTargetTypes] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setPage(1);
  }, [action, targetType, debouncedKeyword]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await adminAuditLogs({
        action: action || undefined,
        target_type: targetType || undefined,
        keyword: debouncedKeyword,
        page,
        page_size: PAGE_SIZE,
      });
      setRows(data.logs);
      setTotal(data.total);
      if (data.actions.length) setActions(data.actions);
      if (data.target_types.length) setTargetTypes(data.target_types);
      setError('');
    } catch (e) {
      setError(humanizeAdminError(e, '加载审计日志失败，请稍后重试'));
    } finally {
      setLoading(false);
    }
  }, [action, targetType, debouncedKeyword, page]);

  useEffect(() => { void load(); }, [load]);

  const reset = () => {
    setAction('');
    setTargetType('');
    setKeyword('');
    setPage(1);
  };

  return (
    <AdminListPage
      filters={(
        <>
          <Select
            style={{ width: 180 }}
            value={action}
            options={[{ value: '', label: '全部动作' }, ...actions]}
            onChange={setAction}
          />
          <Select
            style={{ width: 160 }}
            value={targetType}
            options={[
              { value: '', label: '全部对象' },
              ...targetTypes.map((t) => ({ value: t, label: TARGET_LABEL[t] ?? t })),
            ]}
            onChange={setTargetType}
          />
          <Input
            allowClear
            placeholder="操作人 / 对象 / 关键词"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            style={{ width: 240 }}
          />
          <Button type="link" className="admin-filter-link" onClick={reset}>清空筛选</Button>
          <Button type="link" className="admin-filter-link" onClick={() => void load()}>刷新</Button>
        </>
      )}
      extra={(
        <>
          <Alert type="info" showIcon message="审计日志只读。敏感内容（密码/token）在写入时就会被拒绝。" />
          {error && <Alert type="error" showIcon message={error} style={{ marginTop: 8 }} />}
        </>
      )}
      footer={<AdminPager total={total} page={page} onChange={setPage} />}
    >
      <Table<AuditRow>
        rowKey="id"
        loading={loading}
        dataSource={rows}
        pagination={false}
        tableLayout="auto"
        locale={{ emptyText: <Empty description="暂无审计记录" /> }}
        columns={[
          { title: '时间', dataIndex: 'created_at', render: (v) => fmtShanghai(v) },
          {
            title: '操作人',
            render: (_, r) => (
              <span>
                {r.actor_username}
                {r.actor_role && <span className="admin-muted"> · {r.actor_role}</span>}
              </span>
            ),
          },
          { title: '动作', render: (_, r) => <Tag color="blue">{r.action_label ?? r.action}</Tag> },
          {
            title: '对象',
            render: (_, r) => `${TARGET_LABEL[r.target_type] ?? r.target_type}${r.target_label ? ` · ${r.target_label}` : ''}`,
          },
          {
            title: '明细',
            render: (_, r) => {
              const lines = renderDetail(r.action, r.detail);
              return lines.length ? (
                <div className="audit-detail">{lines.map((line, i) => <span key={i}>{line}</span>)}</div>
              ) : '—';
            },
          },
          { title: 'IP', dataIndex: 'ip', render: (v) => v ?? '—' },
        ]}
      />
    </AdminListPage>
  );
}
