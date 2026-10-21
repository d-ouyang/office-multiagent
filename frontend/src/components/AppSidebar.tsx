// 应用侧栏（p6.2→p6.10，参考 RAG AppSidebar）：会话列表 + 底部用户信息（点用户名展开最近用量）/退出。
import { useState } from 'react';

export interface SessionMeta {
  id: string;
  title: string;
  updatedAt: number;
}

export interface SessionUser {
  employee_id: string;
  username: string;
  role: string;
}

export function AppSidebar(props: {
  sessions: SessionMeta[];
  currentId: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  user: SessionUser;
  balance?: number | null;   // p6.4：token 余额
  ledger?: Array<{ task_id?: string; model?: string; reserve?: number; settle?: number; created_at?: string }>; // p6.10：最近流水
  onLogout: () => void;
}) {
  const [showLedger, setShowLedger] = useState(false);
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <span className="brand-dot" />
        office-multiagent
      </div>
      <button className="new-chat" onClick={props.onNew}>
        ＋ 新会话
      </button>
      <div className="session-list">
        {props.sessions.map((s) => (
          <button
            key={s.id}
            className={`session-item ${s.id === props.currentId ? 'active' : ''}`}
            onClick={() => props.onSelect(s.id)}
          >
            <span className="session-title">{s.title}</span>
            <span className="session-time">
              {new Date(s.updatedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
            </span>
          </button>
        ))}
      </div>
      <div className="sidebar-user">
        <div className="user-info">
          <div
            className="user-name clickable"
            title="点击展开最近用量"
            onClick={() => setShowLedger((v) => !v)}
          >
            {props.user.username}
            {props.balance != null && (
              <span className="balance-badge">{props.balance.toLocaleString()}</span>
            )}
          </div>
          <div className="user-meta">
            {props.user.employee_id} · {props.user.role}
          </div>
          {showLedger && props.ledger && props.ledger.length > 0 && (
            <div className="ledger-list">
              {props.ledger
                .filter((l) => l.settle != null)
                .slice(0, 8)
                .map((l, i) => (
                  <div key={i} className="ledger-row">
                    <span className="ledger-model">{l.model || '-'}</span>
                    <span className="ledger-tokens">-{(l.settle ?? 0).toLocaleString()}</span>
                  </div>
                ))}
            </div>
          )}
        </div>
        <button className="logout" onClick={props.onLogout} title="退出登录">
          退出
        </button>
      </div>
    </aside>
  );
}

export default AppSidebar;
