import { useCallback, useEffect, useState } from 'react';

import Pager from '../components/ui/Pager';
import Select from '../components/ui/Select';
import { adminRun, adminTasks, type AdminRunDetail, type AdminTaskRow } from '../lib/api';
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
  const [filter, setFilter] = useState(initial.status);
  const [flag, setFlag] = useState(initial.flag);
  const [taskId, setTaskId] = useState(initial.task_id);
  const [error, setError] = useState('');
  const [detail, setDetail] = useState<AdminRunDetail | null>(null);

  const load = useCallback(async (pg = page, size = pageSize) => {
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
      setError(`加载失败：${(e as Error).message}`);
      return [];
    }
  }, [filter, page, pageSize, flag, taskId]);

  useEffect(() => {
    const sync = () => {
      const q = readQuery();
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
        void adminRun(want).then(setDetail).catch((e) => setError((e as Error).message));
      }
    });
  }, [filter, page, pageSize, load]);

  const openDetail = async (id: string) => {
    try {
      setDetail(await adminRun(id));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="list-page">
      <div className="admin-toolbar">
        <Select
          width={150}
          value={filter}
          placeholder="全部状态"
          options={TASK_STATUS_OPTIONS}
          onChange={(v) => { setFilter(v); setPage(1); }}
        />
        <Select
          width={160}
          value={flag}
          placeholder="全部痕迹"
          options={[
            { value: '', label: '全部痕迹' },
            { value: 'paused', label: '暂停' },
            { value: 'rag', label: '曾检索知识库' },
            { value: 'validation', label: '数字未对齐' },
            { value: 'no_artifact', label: '无产物' },
          ]}
          onChange={(v) => { setFlag(v); setPage(1); }}
        />
        <button type="button" className="admin-btn ghost" onClick={() => void load(page, pageSize)}>刷新</button>
      </div>
      {error && <div className="banner err">{error}</div>}
      <div className="table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>用户</th>
              <th>时间</th>
              <th>任务摘要</th>
              <th>任务耗时</th>
              <th>状态</th>
              <th>任务原因</th>
              <th>任务id</th>
              <th>会话id</th>
              <th>消耗token</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.username ?? '—'}</td>
                <td className="admin-muted nowrap">{fmtShanghai(r.created_at)}</td>
                <td className="admin-task-text" title={r.text}>{r.text || '—'}</td>
                <td className="nowrap">{fmtDuration(r.duration_ms)}</td>
                <td>
                  <span className={`badge ${r.status.startsWith('paused') || r.status === 'failed' ? 'warn' : 'agent'}`}>
                    {STATUS[r.status] ?? r.status}
                  </span>
                </td>
                <td className="admin-muted">{isIncomplete(r.status) && r.pause_reason ? REASON[r.pause_reason] ?? r.pause_reason : '—'}</td>
                <td className="mono admin-muted" title={r.id}>{r.id.slice(0, 10)}</td>
                <td className="mono admin-muted" title={r.session_id || ''}>{(r.session_id || '—').slice(0, 10)}</td>
                <td className="num">{r.tokens_used ? fmtTokens(r.tokens_used) : '—'}</td>
                <td className="admin-ops">
                  <button type="button" className="admin-btn ghost" onClick={() => void openDetail(r.id)}>查看详情</button>
                </td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={10} className="admin-empty">暂无任务</td></tr>}
          </tbody>
        </table>
      </div>
      <Pager total={total} page={page} pageSize={pageSize}
        onPage={(p) => setPage(p)}
        onPageSize={(n) => { setPageSize(n); setPage(1); }}
      />
      {detail && <TaskDetailDrawer detail={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}
