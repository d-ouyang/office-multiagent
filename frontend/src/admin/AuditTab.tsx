import { useCallback, useEffect, useState } from 'react';

import { adminAuditLogs, type AuditRow } from '../lib/api';
import { AdminListPage, AdminPager, PAGE_SIZE } from './AdminListPage';
import { Ellipsis } from './ellipsis';
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
      extra={error ? <Alert type="error" showIcon message={error} /> : null}
      footer={<AdminPager total={total} page={page} onChange={setPage} />}
    >
      <Table<AuditRow>
        rowKey="id"
        loading={loading}
        dataSource={rows}
        pagination={false}
        tableLayout="fixed"
        locale={{ emptyText: <Empty description="暂无审计记录" /> }}
        columns={[
          {
            title: '时间',
            dataIndex: 'created_at',
            width: '18%',
            render: (v) => fmtShanghai(v),
          },
          {
            title: '操作人',
            width: '12%',
            ellipsis: { showTitle: false },
            render: (_, r) => {
              const text = r.actor_role ? `${r.actor_username} · ${r.actor_role}` : r.actor_username;
              return <Ellipsis>{text}</Ellipsis>;
            },
          },
          {
            title: '动作',
            width: '14%',
            render: (_, r) => <Tag color="blue">{r.action_label ?? r.action}</Tag>,
          },
          {
            title: '对象',
            width: '14%',
            ellipsis: { showTitle: false },
            render: (_, r) => {
              const text = `${TARGET_LABEL[r.target_type] ?? r.target_type}${r.target_label ? ` · ${r.target_label}` : ''}`;
              return <Ellipsis>{text}</Ellipsis>;
            },
          },
          {
            title: 'IP',
            dataIndex: 'ip',
            width: '12%',
            ellipsis: { showTitle: false },
            render: (v) => <Ellipsis>{v ?? '—'}</Ellipsis>,
          },
          {
            title: '明细',
            width: '30%',
            className: 'admin-cell-wrap',
            render: (_, r) => renderDetail(r.action, r.detail).join('；') || '—',
          },
        ]}
      />
    </AdminListPage>
  );
}
