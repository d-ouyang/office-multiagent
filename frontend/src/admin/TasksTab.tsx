import dayjs, { type Dayjs } from 'dayjs';
import { useCallback, useEffect, useState } from 'react';

import { adminRun, adminTasks, type AdminRunDetail, type AdminTaskRow } from '../lib/api';
import { AdminListPage, AdminPager, PAGE_SIZE } from './AdminListPage';
import { CopyCell, Ellipsis } from './ellipsis';
import { humanizeAdminError } from './errors';
import { fmtDuration, fmtShanghai, fmtTokens, STATUS } from './format';
import TaskDetailDrawer from './TaskDetailDrawer';
import { Alert, Button, DatePicker, Empty, Input, Select, Table, Tag } from './ui';
import { useDebouncedValue } from './useDebouncedValue';

/** 只有任务摘要不设宽（吃剩余）。任务id / 会话id 必须固定，不能 flex。 */
export const TASK_COL_WIDTH = {
  username: 92,
  employeeId: 110,
  time: 186,
  duration: 102,
  status: 76,
  taskId: 148,
  sessionId: 148,
  token: 110,
  action: 116,
} as const;

export const TASK_COLUMN_TITLES = [
  '用户', '工号', '时间', '任务摘要', '任务耗时', '状态', '任务id', '会话id', '消耗token', '操作',
] as const;

const TASK_STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'done', label: '完成' },
  { value: 'paused_user', label: '用户暂停' },
  { value: 'paused_insufficient_quota', label: '配额暂停' },
  { value: 'paused_error', label: '出错暂停' },
  { value: 'resumed', label: '续跑' },
];

function readQuery() {
  const q = new URLSearchParams(window.location.search);
  return {
    status: q.get('status') || '',
    flag: q.get('flag') || '',
    task_id: q.get('task_id') || '',
    session_id: q.get('session_id') || '',
    user_id: q.get('user_id') || '',
    q: q.get('q') || '',
    date: q.get('date') || '',
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
  const [userQ, setUserQ] = useState(initial.q);
  const [date, setDate] = useState(initial.date);
  const [taskId, setTaskId] = useState(initial.task_id);
  const [error, setError] = useState('');
  const [detail, setDetail] = useState<AdminRunDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const debouncedQ = useDebouncedValue(userQ, 300);

  const load = useCallback(async (pg = page) => {
    setLoading(true);
    try {
      const q = readQuery();
      const data = await adminTasks(filter || undefined, pg, PAGE_SIZE, flag || undefined, {
        task_id: q.task_id || taskId || undefined,
        session_id: q.session_id || undefined,
        user_id: q.user_id ? Number(q.user_id) : undefined,
        q: debouncedQ || undefined,
        date: date || undefined,
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
  }, [filter, page, flag, taskId, debouncedQ, date]);

  useEffect(() => {
    const sync = () => {
      const q = readQuery();
      setFilter(q.status);
      setFlag(q.flag);
      setUserQ(q.q);
      setDate(q.date);
      setTaskId(q.task_id);
      setPage(1);
    };
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);

  useEffect(() => {
    setPage(1);
  }, [debouncedQ, date]);

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
    setUserQ('');
    setDate('');
    setPage(1);
    const url = new URL(window.location.href);
    url.search = '';
    window.history.replaceState({}, '', `${url.pathname}${url.hash}`);
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
          <Input
            allowClear
            placeholder="用户名 / 工号"
            value={userQ}
            onChange={(e) => setUserQ(e.target.value)}
            style={{ width: 220 }}
          />
          <DatePicker
            allowClear
            placeholder="时间"
            format="YYYY-MM-DD"
            value={date ? dayjs(date) : null}
            onChange={(v: Dayjs | null) => { setDate(v ? v.format('YYYY-MM-DD') : ''); setPage(1); }}
            style={{ width: 190 }}
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
        className="admin-tasks-table"
        loading={loading}
        dataSource={rows}
        pagination={false}
        tableLayout="fixed"
        locale={{ emptyText: <Empty description="暂无任务" /> }}
        columns={[
          {
            title: '用户',
            dataIndex: 'username',
            width: TASK_COL_WIDTH.username,
            ellipsis: { showTitle: false },
            render: (v) => <Ellipsis>{v ?? '—'}</Ellipsis>,
          },
          {
            title: '工号',
            dataIndex: 'employee_id',
            width: TASK_COL_WIDTH.employeeId,
            ellipsis: { showTitle: false },
            render: (v) => <Ellipsis>{v ?? '—'}</Ellipsis>,
          },
          {
            title: '时间',
            dataIndex: 'created_at',
            width: TASK_COL_WIDTH.time,
            className: 'admin-cell-time',
            render: (v) => fmtShanghai(v),
          },
          {
            title: '任务摘要',
            dataIndex: 'text',
            ellipsis: { showTitle: false },
            render: (v) => <CopyCell text={v || '—'} />,
          },
          {
            title: '任务耗时',
            dataIndex: 'duration_ms',
            width: TASK_COL_WIDTH.duration,
            render: (v) => fmtDuration(v),
          },
          {
            title: '状态',
            dataIndex: 'status',
            width: TASK_COL_WIDTH.status,
            render: (status: string) => (
              <Tag color={status.startsWith('paused') || status === 'failed' ? 'warning' : 'blue'}>
                {STATUS[status] ?? status}
              </Tag>
            ),
          },
          {
            title: '任务id',
            dataIndex: 'id',
            width: TASK_COL_WIDTH.taskId,
            ellipsis: { showTitle: false },
            render: (v) => <CopyCell className="admin-mono" text={v} />,
          },
          {
            title: '会话id',
            dataIndex: 'session_id',
            width: TASK_COL_WIDTH.sessionId,
            ellipsis: { showTitle: false },
            render: (id?: string | null) => <CopyCell className="admin-mono" text={id || '—'} />,
          },
          {
            title: '消耗token',
            dataIndex: 'tokens_used',
            width: TASK_COL_WIDTH.token,
            align: 'right',
            render: (n: number) => (n ? fmtTokens(n) : '—'),
          },
          {
            title: '操作',
            width: TASK_COL_WIDTH.action,
            render: (_, r) => <Button type="link" onClick={() => void openDetail(r.id)}>查看详情</Button>,
          },
        ]}
      />
      <TaskDetailDrawer detail={detail} onClose={() => setDetail(null)} />
    </AdminListPage>
  );
}
