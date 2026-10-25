import type { AdminRunDetail } from '../lib/api';
import { fmtDuration, fmtShanghai, fmtTokens, REASON, STATUS } from './format';

export default function TaskDetailDrawer({
  detail,
  onClose,
}: {
  detail: AdminRunDetail;
  onClose: () => void;
}) {
  const flow = detail.flow;
  const nodes = flow?.nodes ?? [];
  const path = new Set(flow?.path ?? []);

  return (
    <div className="admin-drawer-mask" onClick={onClose}>
      <aside className="admin-drawer" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <header className="admin-drawer-head">
          <div>
            <h3>任务详情</h3>
            <p className="admin-sub">{fmtShanghai(detail.created_at)} · {fmtDuration(detail.duration_ms)}</p>
          </div>
          <button type="button" className="admin-btn ghost" onClick={onClose}>关闭</button>
        </header>

        <div className="admin-drawer-body">
          <div className="admin-detail-head">
            <span className={`badge ${detail.status.startsWith('paused') || detail.status === 'failed' ? 'warn' : 'agent'}`}>
              {STATUS[detail.status] ?? detail.status}
            </span>
            <span className="admin-muted">{detail.username ?? '—'} · {detail.model || '未记模型'}</span>
          </div>

          <h4 className="admin-sec">问句</h4>
          <p className="admin-quote">{detail.text || flow?.question || '—'}</p>

          <h4 className="admin-sec">实走路径</h4>
          <div className="admin-flow-card">
            {nodes.length === 0 && <p className="admin-sub">没有可用的节点流（无 trace）。</p>}
            <ol className="admin-flow">
              {nodes.map((node, i) => {
                const on = path.has(node.key);
                return (
                  <li key={node.key} className={`admin-flow-node ${node.kind} ${on ? 'on' : 'off'}`}>
                    <i>{on ? i + 1 : '·'}</i>
                    <div>
                      <strong>{node.label}</strong>
                      {node.detail && <p>{node.detail}</p>}
                    </div>
                  </li>
                );
              })}
            </ol>
          </div>

          <h4 className="admin-sec">关键指标</h4>
          <dl className="admin-kv">
            <div><dt>用户</dt><dd>{detail.username ?? '—'}</dd></div>
            <div><dt>任务耗时</dt><dd>{fmtDuration(detail.duration_ms)}</dd></div>
            <div><dt>消耗 token</dt><dd>{detail.tokens_used ? fmtTokens(detail.tokens_used) : '—'}</dd></div>
            <div><dt>任务原因</dt><dd>{detail.pause_reason ? REASON[detail.pause_reason] ?? detail.pause_reason : '—'}</dd></div>
            <div><dt>任务 id</dt><dd className="mono">{detail.id}</dd></div>
            <div><dt>会话 id</dt><dd className="mono">{detail.session_id || '—'}</dd></div>
            <div><dt>工具</dt><dd>{detail.tools?.length ? detail.tools.join(' → ') : '无'}</dd></div>
            <div><dt>产物</dt><dd>{detail.artifacts?.length ? detail.artifacts.join('、') : '无'}</dd></div>
            <div>
              <dt>知识库身份</dt>
              <dd className={detail.identity_mismatch ? 'warn-text' : ''}>
                调用 {detail.rag_username || '—'}，办公用户 {detail.office_username || detail.username || '—'}
                {detail.identity_mismatch ? '（不一致）' : ''}
              </dd>
            </div>
            {detail.validation_note && <div><dt>校验</dt><dd>{detail.validation_note}</dd></div>}
          </dl>
        </div>
      </aside>
    </div>
  );
}
