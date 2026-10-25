import { Alert, Button, Empty, Form, Input, Select, Space, Table, Tag } from 'antd';
import { useCallback, useEffect, useState } from 'react';

import { adminAuditLogs, type AuditRow } from '../lib/api';
import { humanizeAdminError } from './errors';
import { fmtShanghai, renderDetail, TARGET_LABEL } from './format';

export default function AuditTab() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [draftAction, setDraftAction] = useState('');
  const [draftTarget, setDraftTarget] = useState('');
  const [draftKeyword, setDraftKeyword] = useState('');
  const [action, setAction] = useState('');
  const [targetType, setTargetType] = useState('');
  const [keyword, setKeyword] = useState('');
  const [actions, setActions] = useState<Array<{ value: string; label: string }>>([]);
  const [targetTypes, setTargetTypes] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await adminAuditLogs({ action: action || undefined, target_type: targetType || undefined, keyword, page, page_size: pageSize });
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
  }, [action, targetType, keyword, page, pageSize]);

  useEffect(() => { void load(); }, [load]);

  const search = () => {
    setAction(draftAction);
    setTargetType(draftTarget);
    setKeyword(draftKeyword);
    setPage(1);
  };

  const reset = () => {
    setDraftAction('');
    setDraftTarget('');
    setDraftKeyword('');
    setAction('');
    setTargetType('');
    setKeyword('');
    setPage(1);
  };

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Form layout="inline" className="admin-filter-form" onFinish={search}>
        <Form.Item>
          <Select
            style={{ width: 180 }}
            value={draftAction}
            options={[{ value: '', label: '全部动作' }, ...actions]}
            onChange={setDraftAction}
          />
        </Form.Item>
        <Form.Item>
          <Select
            style={{ width: 150 }}
            value={draftTarget}
            options={[
              { value: '', label: '全部对象' },
              ...targetTypes.map((t) => ({ value: t, label: TARGET_LABEL[t] ?? t })),
            ]}
            onChange={setDraftTarget}
          />
        </Form.Item>
        <Form.Item>
          <Input
            allowClear
            placeholder="操作人 / 对象 / 关键词"
            value={draftKeyword}
            onChange={(e) => setDraftKeyword(e.target.value)}
            style={{ width: 220 }}
          />
        </Form.Item>
        <Form.Item>
          <Space>
            <Button type="primary" htmlType="submit">搜索</Button>
            <Button onClick={reset}>重置</Button>
          </Space>
        </Form.Item>
      </Form>
      <Alert type="info" showIcon message="审计日志只读。敏感内容（密码/token）在写入时就会被拒绝。" />
      {error && <Alert type="error" showIcon message={error} />}
      <Table<AuditRow>
        rowKey="id"
        loading={loading}
        dataSource={rows}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (n) => `共 ${n} 条`,
          onChange: (p, s) => { setPage(p); setPageSize(s); },
        }}
        locale={{ emptyText: <Empty description="暂无审计记录" /> }}
        columns={[
          { title: '时间', dataIndex: 'created_at', render: (v) => fmtShanghai(v), width: 180 },
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
    </Space>
  );
}
