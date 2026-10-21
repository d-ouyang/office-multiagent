// 应用侧栏（p6.2→p6.12，参考 RAG AppSidebar / WorkBuddy）：会话列表（相对时间 + 超出 10 条折叠）+ 底部用户信息（点用户名展开最近用量）/退出。
import { useState } from 'react';

export interface SessionMeta {
  id: string;
  title: string;
  updatedAt: number; // 毫秒时间戳（后端 updated_at=最后一次问答时间）
}

export interface SessionUser {
  employee_id: string;
  username: string;
  role: string;
}

const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;

/** p6.12：会话时间显示规则——1 分钟内 HH:MM；超 1 分钟 XX分钟前；XX小时前；XX天前；超 7 天 MM月DD日。 */
export function formatSessionTime(ts: number, now: number = Date.now()): string {
  if (!Number.isFinite(ts) || ts <= 0) return '';
  const diff = now - ts;
  if (diff < MIN) {
    return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  }
  if (diff < HOUR) {
    return `${Math.floor(diff / MIN)}分钟前`;
  }
  if (diff < DAY) {
    return `${Math.floor(diff / HOUR)}小时前`;
  }
  if (diff < WEEK) {
    return `${Math.floor(diff / DAY)}天前`;
  }
  const d = new Date(ts);
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

const VISIBLE_LIMIT = 10; // p6.12：默认最多显示 10 条，超出"查看更多 (N)"展开全部

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
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? props.sessions : props.sessions.slice(0, VISIBLE_LIMIT);
  const hidden = props.sessions.length - visible.length;
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
        {visible.map((s) => (
          <button
            key={s.id}
            className={`session-item ${s.id === props.currentId ? 'active' : ''}`}
            onClick={() => props.onSelect(s.id)}
          >
            <span className="session-title">{s.title}</span>
            <span className="session-time">{formatSessionTime(s.updatedAt)}</span>
          </button>
        ))}
        {hidden > 0 && (
          <button className="session-more" onClick={() => setExpanded(true)}>
            查看更多 ({props.sessions.length})
          </button>
        )}
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
