// 应用侧栏（p6.2→p6.12，参考 RAG AppSidebar / WorkBuddy）：会话列表（相对时间 + 超出 10 条折叠）+ 底部用户信息（点用户名展开最近用量）/退出。
import { useEffect, useRef, useState } from 'react';

import { APP_BLURB, APP_VERSION } from '../version';
import { AccountPanel, type UsageSummary } from './AccountPanel';

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

const PAGE_SIZE = 10; // p6.12c：分页展开——默认 10 条，每次"查看更多"加载下一条

export function AppSidebar(props: {
  sessions: SessionMeta[];
  currentId: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  user: SessionUser;
  balance?: number | null;
  usage?: UsageSummary | null;
  modelName?: string;
  onLogout: () => void;
}) {
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [accountOpen, setAccountOpen] = useState(false);
  const accountRef = useRef<HTMLDivElement>(null);
  const visible = props.sessions.slice(0, visibleCount);
  const remaining = props.sessions.length - visible.length;

  useEffect(() => {
    if (!accountOpen) return undefined;
    const onDown = (e: PointerEvent) => {
      if (!accountRef.current?.contains(e.target as Node)) setAccountOpen(false);
    };
    document.addEventListener('pointerdown', onDown);
    return () => document.removeEventListener('pointerdown', onDown);
  }, [accountOpen]);
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <span className="brand-dot" />
        <div className="brand-copy">
          <div className="brand-name">office-multiagent</div>
          <div className="brand-blurb">{APP_BLURB}</div>
          <div className="brand-version">{APP_VERSION}</div>
        </div>
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
        {/* p6.12c：未展开完 → "查看更多 (剩余N) | 收起"；全部展示完 → 只剩"收起" */}
        {(remaining > 0 || visibleCount > PAGE_SIZE) && (
          <div className="session-more-row">
            {remaining > 0 && (
              <button
                className="session-more"
                onClick={() => setVisibleCount((c) => c + PAGE_SIZE)}
              >
                查看更多 ({remaining})
              </button>
            )}
            {remaining > 0 && visibleCount > PAGE_SIZE && <span className="more-divider">|</span>}
            {visibleCount > PAGE_SIZE && (
              <button className="session-more" onClick={() => setVisibleCount(PAGE_SIZE)}>
                收起
              </button>
            )}
          </div>
        )}
      </div>
      <div className="sidebar-user" ref={accountRef}>
        {accountOpen && (
          <AccountPanel
            user={props.user}
            balance={props.balance ?? null}
            usage={props.usage ?? null}
            modelName={props.modelName || 'DeepSeek V3'}
            onClose={() => setAccountOpen(false)}
            onLogout={props.onLogout}
          />
        )}
        <button type="button" className="user-chip" onClick={() => setAccountOpen((v) => !v)} aria-expanded={accountOpen}>
          <span className="account-avatar sm" aria-hidden="true">{(props.user.username || '?').slice(0, 1).toUpperCase()}</span>
          <span className="user-info">
            <span className="user-name">{props.user.username}</span>
            <span className="user-meta">{props.user.employee_id} · {props.user.role}</span>
          </span>
        </button>
      </div>
    </aside>
  );
}

export default AppSidebar;
