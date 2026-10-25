import { useCallback, useEffect, useState } from 'react';

import { adminRun, adminTasks, type AdminRunDetail, type AdminTaskRow } from '../lib/api';
import { AdminListPage, AdminPager, PAGE_SIZE } from './AdminListPage';
import { humanizeAdminError } from './errors';
import { fmtDuration, fmtShanghai, fmtTokens, isIncomplete, REASON, STATUS } from './format';
import TaskDetailDrawer from './TaskDetailDrawer';
import { Alert, Button, Empty, Select, Table, Tag } from './ui';

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
  const [filter, setFilter] = useState(initial.status);
  const [flag, setFlag] = useState(initial.flag);
  const [taskId, setTaskId] = useState(initial.task_id);
  const [error, setError] = useState('');
  const [detail, setDetail] = useState<AdminRunDetail | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (pg = page) => {
    setLoading(true);
    try {
      const q = readQuery();
      const data = await adminTasks(filter || undefined, pg, PAGE_SIZE, flag || undefined, {
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
  }, [filter, page, flag, taskId]);

  useEffect(() => {
    const sync = () => {
      const q = readQuery();
      setFilter(q.status);
      setFlag(q.flag);
      setTaskId(q.task_id);
      setPage(1);
    };
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);

  useEffect(() => {
    void load(page).then((tasks) => {
      const q = readQuery();
      const want = q.task_id || (q.open ? tasks[0]?.id : '');
      if (want) {
        void adminRun(want).then(setDetail).catch((e) => setError(humanizeAdminError(e, '加载任务详情失败，请稍后重试')));
      }
    });
  }, [filter, page, flag, load]);

  const openDetail = async (id: string) => {
    try {
      setDetail(await adminRun(id));
    } catch (e) {
      setError(humanizeAdminError(e, '加载任务详情失败，请稍后重试'));
    }
  };

  const reset = () => {
    setFilter('');
    setFlag('');
    setPage(1);
  };

  return (
    <AdminListPage
      filters={(
        <>
          <Select
            style={{ width: 170 }}
            value={filter}
            options={TASK_STATUS_OPTIONS}
            onChange={(v) => { setFilter(v); setPage(1); }}
          />
          <Select
            style={{ width: 180 }}
            value={flag}
            options={FLAG_OPTIONS}
            onChange={(v) => { setFlag(v); setPage(1); }}
          />
          <Button type="link" className="admin-filter-link" onClick={reset}>清空筛选</Button>
          <Button type="link" className="admin-filter-link" onClick={() => void load(page)}>刷新</Button>
        </>
      )}
      extra={error ? <Alert type="error" showIcon message={error} /> : null}
      footer={<AdminPager total={total} page={page} onChange={setPage} />}
    >
      <Table<AdminTaskRow>
        rowKey="id"
        loading={loading}
        dataSource={rows}
        pagination={false}
        tableLayout="auto"
        locale={{ emptyText: <Empty description="暂无任务" /> }}
        columns={[
          { title: '用户', dataIndex: 'username', render: (v) => v ?? '—' },
          { title: '时间', dataIndex: 'created_at', render: (v) => fmtShanghai(v) },
          { title: '任务摘要', dataIndex: 'text', render: (v) => v || '—' },
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
          { title: '任务id', dataIndex: 'id' },
          { title: '会话id', dataIndex: 'session_id', render: (id?: string | null) => id || '—' },
          { title: '消耗token', dataIndex: 'tokens_used', align: 'right', render: (n: number) => (n ? fmtTokens(n) : '—') },
          {
            title: '',
            render: (_, r) => <Button type="link" onClick={() => void openDetail(r.id)}>查看详情</Button>,
          },
        ]}
      />
      <TaskDetailDrawer detail={detail} onClose={() => setDetail(null)} />
    </AdminListPage>
  );
}
