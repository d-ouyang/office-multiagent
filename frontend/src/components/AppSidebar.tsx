// 应用侧栏（p6.2，参考 RAG AppSidebar）：会话列表 + 底部用户信息/退出。
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
  onLogout: () => void;
}) {
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
          <div className="user-name">{props.user.username}</div>
          <div className="user-meta">
            {props.user.employee_id} · {props.user.role}
            {props.balance != null && <> · 余额 {props.balance.toLocaleString()}</>}
          </div>
        </div>
        <button className="logout" onClick={props.onLogout} title="退出登录">
          退出
        </button>
      </div>
    </aside>
  );
}

export default AppSidebar;
