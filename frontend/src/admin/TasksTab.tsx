import { Alert, Button, Empty, Form, Select, Space, Table, Tag } from 'antd';
import { useCallback, useEffect, useState } from 'react';

import { adminRun, adminTasks, type AdminRunDetail, type AdminTaskRow } from '../lib/api';
import { humanizeAdminError } from './errors';
import { fmtDuration, fmtShanghai, fmtTokens, isIncomplete, REASON, STATUS } from './format';
import TaskDetailDrawer from './TaskDetailDrawer';

const TASK_STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'done', label: '完成' },
  { value: 'paused_user', label: '用户暂停' },
  { value: 'paused_insufficient_quota', label: '配额暂停' },
  { value: 'paused_error', label: '出错暂停' },
  { value: 'resumed', label: '续跑' },
];

const FLAG_OPTIONS = [
  { value: '', label: '全部痕迹' },
  { value: 'paused', label: '暂停' },
  { value: 'rag', label: '曾检索知识库' },
  { value: 'validation', label: '数字未对齐' },
  { value: 'no_artifact', label: '无产物' },
];

function readQuery() {
  const q = new URLSearchParams(window.location.search);
  return {
    status: q.get('status') || '',
    flag: q.get('flag') || '',
    task_id: q.get('task_id') || '',
    session_id: q.get('session_id') || '',
    user_id: q.get('user_id') || '',
    open: q.get('open') === '1',
  };
}

export default function TasksTab() {
  const initial = readQuery();
  const [rows, setRows] = useState<AdminTaskRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [draftStatus, setDraftStatus] = useState(initial.status);
  const [draftFlag, setDraftFlag] = useState(initial.flag);
  const [filter, setFilter] = useState(initial.status);
  const [flag, setFlag] = useState(initial.flag);
  const [taskId, setTaskId] = useState(initial.task_id);
  const [error, setError] = useState('');
  const [detail, setDetail] = useState<AdminRunDetail | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (pg = page, size = pageSize) => {
    setLoading(true);
    try {
      const q = readQuery();
      const data = await adminTasks(filter || undefined, pg, size, flag || undefined, {
        task_id: q.task_id || taskId || undefined,
        session_id: q.session_id || undefined,
        user_id: q.user_id ? Number(q.user_id) : undefined,
      });
      setRows(data.tasks);
      setTotal(data.total);
      setError('');
      return data.tasks;
    } catch (e) {
      setError(humanizeAdminError(e, '加载任务列表失败，请稍后重试'));
      return [];
    } finally {
      setLoading(false);
    }
  }, [filter, page, pageSize, flag, taskId]);

  useEffect(() => {
    const sync = () => {
      const q = readQuery();
      setDraftStatus(q.status);
      setDraftFlag(q.flag);
      setFilter(q.status);
      setFlag(q.flag);
      setTaskId(q.task_id);
    };
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);

  useEffect(() => {
    void load(page, pageSize).then((tasks) => {
      const q = readQuery();
      const want = q.task_id || (q.open ? tasks[0]?.id : '');
      if (want) {
        void adminRun(want).then(setDetail).catch((e) => setError(humanizeAdminError(e, '加载任务详情失败，请稍后重试')));
      }
    });
  }, [filter, page, pageSize, load]);

  const openDetail = async (id: string) => {
    try {
      setDetail(await adminRun(id));
    } catch (e) {
      setError(humanizeAdminError(e, '加载任务详情失败，请稍后重试'));
    }
  };

  const search = () => {
    setFilter(draftStatus);
    setFlag(draftFlag);
    setPage(1);
  };

  const reset = () => {
    setDraftStatus('');
    setDraftFlag('');
    setFilter('');
    setFlag('');
    setPage(1);
  };

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Form layout="inline" className="admin-filter-form" onFinish={search}>
        <Form.Item>
          <Select
            style={{ width: 160 }}
            value={draftStatus}
            options={TASK_STATUS_OPTIONS}
            onChange={setDraftStatus}
          />
        </Form.Item>
        <Form.Item>
          <Select
            style={{ width: 170 }}
            value={draftFlag}
            options={FLAG_OPTIONS}
            onChange={setDraftFlag}
          />
        </Form.Item>
        <Form.Item>
          <Space>
            <Button type="primary" htmlType="submit">搜索</Button>
            <Button onClick={reset}>重置</Button>
          </Space>
        </Form.Item>
      </Form>
      {error && <Alert type="error" showIcon message={error} />}
      <Table<AdminTaskRow>
        rowKey="id"
        loading={loading}
        dataSource={rows}
        scroll={{ x: 1100 }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (n) => `共 ${n} 条`,
          onChange: (p, s) => { setPage(p); setPageSize(s); },
        }}
        locale={{ emptyText: <Empty description="暂无任务" /> }}
        columns={[
          { title: '用户', dataIndex: 'username', render: (v) => v ?? '—' },
          { title: '时间', dataIndex: 'created_at', render: (v) => fmtShanghai(v), width: 180 },
          { title: '任务摘要', dataIndex: 'text', ellipsis: true, render: (v) => v || '—' },
          { title: '任务耗时', dataIndex: 'duration_ms', render: (v) => fmtDuration(v) },
          {
            title: '状态',
            dataIndex: 'status',
            render: (status: string) => (
              <Tag color={status.startsWith('paused') || status === 'failed' ? 'warning' : 'blue'}>
                {STATUS[status] ?? status}
              </Tag>
            ),
          },
          {
            title: '任务原因',
            render: (_, r) => (isIncomplete(r.status) && r.pause_reason ? REASON[r.pause_reason] ?? r.pause_reason : '—'),
          },
          { title: '任务id', dataIndex: 'id', render: (id: string) => id.slice(0, 10) },
          { title: '会话id', dataIndex: 'session_id', render: (id?: string | null) => (id || '—').slice(0, 10) },
          { title: '消耗token', dataIndex: 'tokens_used', align: 'right', render: (n: number) => (n ? fmtTokens(n) : '—') },
          {
            title: '',
            render: (_, r) => <Button type="link" onClick={() => void openDetail(r.id)}>查看详情</Button>,
          },
        ]}
      />
      <TaskDetailDrawer detail={detail} onClose={() => setDetail(null)} />
    </Space>
  );
}
