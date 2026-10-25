import { useCallback, useEffect, useState } from 'react';

import Pager from '../components/ui/Pager';
import Select from '../components/ui/Select';
import { adminAuditLogs, type AuditRow } from '../lib/api';
import { fmtShanghai, renderDetail, TARGET_LABEL } from './format';

export default function AuditTab() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [action, setAction] = useState('');
  const [targetType, setTargetType] = useState('');
  const [keyword, setKeyword] = useState('');
  const [actions, setActions] = useState<Array<{ value: string; label: string }>>([]);
  const [targetTypes, setTargetTypes] = useState<string[]>([]);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const data = await adminAuditLogs({ action: action || undefined, target_type: targetType || undefined, keyword, page, page_size: pageSize });
      setRows(data.logs);
      setTotal(data.total);
      if (data.actions.length) setActions(data.actions);
      if (data.target_types.length) setTargetTypes(data.target_types);
      setError('');
    } catch (e) {
      setError(`加载失败：${(e as Error).message}`);
    }
  }, [action, targetType, keyword, page, pageSize]);

  useEffect(() => { void load(); }, [load]);

  return (
    <div className="list-page">
      <div className="admin-toolbar wrap">
        <Select
          width={170}
          value={action}
          placeholder="全部动作"
          options={[{ value: '', label: '全部动作' }, ...actions.map((a) => ({ value: a.value, label: a.label }))]}
          onChange={(v) => { setAction(v); setPage(1); }}
        />
        <Select
          width={130}
          value={targetType}
          placeholder="全部对象"
          options={[
            { value: '', label: '全部对象' },
            ...targetTypes.map((t) => ({ value: t, label: TARGET_LABEL[t] ?? t })),
          ]}
          onChange={(v) => { setTargetType(v); setPage(1); }}
        />
        <input
          className="admin-search"
          placeholder="操作人 / 对象 / 关键词"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { setPage(1); void load(); } }}
        />
        <button type="button" className="admin-btn ghost" onClick={() => void load()}>刷新</button>
      </div>
      <p className="admin-sub">审计日志只读。敏感内容（密码/token）在写入时就会被拒绝。</p>
      {error && <div className="banner err">{error}</div>}
      <div className="table-wrap">
        <table className="admin-table">
          <thead>
            <tr><th>时间</th><th>操作人</th><th>动作</th><th>对象</th><th>明细</th><th>IP</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="admin-muted nowrap">{fmtShanghai(r.created_at)}</td>
                <td>
                  {r.actor_username}
                  {r.actor_role && <span className="admin-muted"> · {r.actor_role}</span>}
                </td>
                <td><span className="badge agent">{r.action_label ?? r.action}</span></td>
                <td className="admin-muted">
                  {TARGET_LABEL[r.target_type] ?? r.target_type}
                  {r.target_label ? ` · ${r.target_label}` : ''}
                </td>
                <td>
                  <div className="audit-detail">
                    {renderDetail(r.action, r.detail).length === 0 && <span>—</span>}
                    {renderDetail(r.action, r.detail).map((line, i) => (
                      <span key={i}>{line}</span>
                    ))}
                  </div>
                </td>
                <td className="admin-muted">{r.ip ?? '—'}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={6} className="admin-empty">暂无审计记录</td></tr>}
          </tbody>
        </table>
      </div>
      <Pager total={total} page={page} pageSize={pageSize}
        onPage={setPage}
        onPageSize={(n) => { setPageSize(n); setPage(1); }}
      />
    </div>
  );
}
