// 应用侧栏（p6.2→p6.12，参考 RAG AppSidebar / WorkBuddy）：会话列表（相对时间 + 超出 10 条折叠）+ 底部用户信息（点用户名展开最近用量）/退出。
import { useEffect, useRef, useState } from 'react';

import { APP_BLURB, APP_VERSION } from '../version';
import { AccountPanel, type UsageSummary } from './AccountPanel';

export interface SessionMeta {
  id: string;
  title: string;
  updatedAt: number; // 毫秒时间戳（后端 updated_at=最后一次问答时间）
  pinned?: boolean;
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

function SessionTitle({ text, scrolling }: { text: string; scrolling: boolean }) {
  const outer = useRef<HTMLSpanElement>(null);
  const inner = useRef<HTMLSpanElement>(null);
  const [overflow, setOverflow] = useState(false);
  useEffect(() => {
    const box = outer.current;
    const label = inner.current;
    if (!box || !label) return;
    setOverflow(label.scrollWidth > box.clientWidth + 1);
  }, [text, scrolling]);
  const run = scrolling && overflow;
  return (
    <span className="session-title" ref={outer}>
      <span className={`session-title-inner ${run ? 'marquee' : ''}`}>
        <span ref={inner}>{text}</span>
        {run && <span aria-hidden="true">{text}</span>}
      </span>
    </span>
  );
}

export function AppSidebar(props: {
  sessions: SessionMeta[];
  currentId: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRename?: (id: string, title: string) => void;
  onPin?: (id: string, pinned: boolean) => void;
  onDelete?: (id: string) => void;
  user: SessionUser;
  balance?: number | null;
  usage?: UsageSummary | null;
  modelName?: string;
  onLogout: () => void;
  /** p7.1：管理端入口（仅 admin/superadmin 传入；不传则不显示） */
  onOpenAdmin?: () => void;
}) {
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [accountOpen, setAccountOpen] = useState(false);
  const [hoverId, setHoverId] = useState('');
  const [menuId, setMenuId] = useState('');
  const [renamingId, setRenamingId] = useState('');
  const [renameText, setRenameText] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<SessionMeta | null>(null);
  const accountRef = useRef<HTMLDivElement>(null);
  const visible = props.sessions.slice(0, visibleCount);
  const remaining = props.sessions.length - visible.length;

  useEffect(() => {
    if (!accountOpen && !menuId) return undefined;
    const onDown = (e: PointerEvent) => {
      const target = e.target as HTMLElement;
      if (accountOpen && !accountRef.current?.contains(target)) setAccountOpen(false);
      if (menuId && !target.closest?.('.session-ops')) setMenuId('');
    };
    document.addEventListener('pointerdown', onDown);
    return () => document.removeEventListener('pointerdown', onDown);
  }, [accountOpen, menuId]);
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <img className="brand-logo" src="/gq_logo.jpg" alt="锅圈" />
        <div className="brand-copy">
          <div className="brand-name">office-multiagent</div>
          <div className="brand-blurb">{APP_BLURB}</div>
          <div className="brand-version">{APP_VERSION}</div>
        </div>
      </div>
      <button className="new-chat" onClick={props.onNew}>
        ＋ 新会话
      </button>
      {props.onOpenAdmin && (
        <button className="admin-entry" type="button" onClick={props.onOpenAdmin}>
          ⚙ 管理（用户与额度）
        </button>
      )}
      <div className="session-list">
        {visible.map((s) => (
          <div
            key={s.id}
            className={`session-item ${s.id === props.currentId ? 'active' : ''} ${menuId === s.id ? 'menu-open' : ''}`}
            onMouseEnter={() => setHoverId(s.id)}
            onMouseLeave={() => setHoverId('')}
          >
            {renamingId === s.id ? (
              <input
                className="session-rename"
                value={renameText}
                autoFocus
                maxLength={60}
                onChange={(e) => setRenameText(e.target.value)}
                onClick={(e) => e.stopPropagation()}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    props.onRename?.(s.id, renameText.trim() || s.title);
                    setRenamingId('');
                  }
                  if (e.key === 'Escape') setRenamingId('');
                }}
                onBlur={() => {
                  props.onRename?.(s.id, renameText.trim() || s.title);
                  setRenamingId('');
                }}
              />
            ) : (
              <button type="button" className="session-open" onClick={() => props.onSelect(s.id)}>
                {s.pinned && <span className="pin-mark" aria-hidden="true">📌</span>}
                <SessionTitle text={s.title} scrolling={hoverId === s.id} />
              </button>
            )}
            <span className="session-time">{formatSessionTime(s.updatedAt)}</span>
            <div className="session-ops">
              <button
                type="button"
                className="session-ops-btn"
                aria-label="更多操作"
                title="更多操作"
                aria-expanded={menuId === s.id}
                onClick={(e) => {
                  e.stopPropagation();
                  setMenuId((current) => (current === s.id ? '' : s.id));
                }}
              >
                ⋯
              </button>
              {menuId === s.id && (
                <div className="session-menu">
                  <button type="button" onClick={() => { props.onPin?.(s.id, !s.pinned); setMenuId(''); }}>
                    <PinIcon />
                    {s.pinned ? '取消置顶' : '置顶'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setRenamingId(s.id);
                      setRenameText(s.title);
                      setMenuId('');
                    }}
                  >
                    <RenameIcon />
                    重命名
                  </button>
                  <button
                    type="button"
                    className="danger"
                    onClick={() => {
                      setDeleteTarget(s);
                      setMenuId('');
                    }}
                  >
                    <TrashIcon />
                    删除会话
                  </button>
                </div>
              )}
            </div>
          </div>
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
      {deleteTarget && (
        <div className="confirm-mask" onClick={() => setDeleteTarget(null)}>
          <div
            className="confirm-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-session-title"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 id="delete-session-title">确认删除会话「{deleteTarget.title}」？</h3>
            <p>该会话下的全部对话消息会一并删除，且无法恢复。</p>
            <div className="confirm-actions">
              <button type="button" className="confirm-cancel" onClick={() => setDeleteTarget(null)}>取消</button>
              <button
                type="button"
                className="confirm-danger"
                onClick={() => {
                  props.onDelete?.(deleteTarget.id);
                  setDeleteTarget(null);
                }}
              >
                删除
              </button>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}

function PinIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
      <path d="M12 17v5" />
      <path d="M9 3h6l1 7 3 3H5l3-3z" />
    </svg>
  );
}

function RenameIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
      <path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  );
}

export default AppSidebar;
