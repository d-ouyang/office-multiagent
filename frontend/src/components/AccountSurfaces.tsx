// 个人中心里那些不该挤在小弹层里的操作：用量、记忆、系统设置、修改密码。
import { useEffect, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

import {
  addMemory,
  changePassword,
  deleteMemory,
  EMPTY_PROFILE,
  getMemoryBundle,
  getSettings,
  saveMemoryProfile,
  saveSetting,
  searchUsage,
  updateMemory,
  type MemoryItem,
  type MemoryProfile,
  type SettingItem,
  type UsageHit,
} from '../lib/api';
import { formatLedgerTime, formatTokens } from '../lib/format';
import { modelDisplayName, type DialogueModel } from './ModelPicker';

function Dialog({
  title,
  onClose,
  wide,
  children,
}: {
  title: string;
  onClose: () => void;
  wide?: boolean;
  children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);
  return createPortal(
    <div className="workspace-dialog-mask" onClick={onClose}>
      <div
        className={`workspace-dialog${wide ? ' wide' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="workspace-dialog-head">
          <h2>{title}</h2>
          <button type="button" aria-label="关闭" onClick={onClose}>×</button>
        </header>
        <div className="workspace-dialog-body">{children}</div>
      </div>
    </div>,
    document.body,
  );
}

export function UsageDialog({
  models,
  onClose,
  onJump,
}: {
  models: DialogueModel[];
  onClose: () => void;
  onJump: (sessionId: string, taskId: string, question: string) => void;
}) {
  const [model, setModel] = useState('');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [minTokens, setMinTokens] = useState('');
  const [maxTokens, setMaxTokens] = useState('');
  const [rows, setRows] = useState<UsageHit[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    searchUsage({ model, start, end, minTokens, maxTokens })
      .then((items) => {
        if (!cancelled) setRows(items);
      })
      .catch((e) => {
        if (!cancelled) setError((e as Error).message);
      });
    return () => {
      cancelled = true;
    };
    // 点「筛选」或第一次打开才查，避免日期还没选完就打一串请求。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  return (
    <Dialog title="用量明细" wide onClose={onClose}>
      <p className="account-note">按实际结算列出。点一行会打开那次提问所在的会话。</p>
      <div className="usage-filters">
        <label>
          模型
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            <option value="">全部</option>
            {models.map((m) => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </select>
        </label>
        <label>
          开始
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label>
          结束
          <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
        <label>
          用量至少
          <input inputMode="numeric" value={minTokens} placeholder="token" onChange={(e) => setMinTokens(e.target.value.replace(/[^\d]/g, ''))} />
        </label>
        <label>
          用量至多
          <input inputMode="numeric" value={maxTokens} placeholder="token" onChange={(e) => setMaxTokens(e.target.value.replace(/[^\d]/g, ''))} />
        </label>
        <button type="button" className="send" onClick={() => setQuery((n) => n + 1)}>筛选</button>
      </div>
      {error && <p className="account-err">{error}</p>}
      {!error && rows === null && <p className="account-note">正在读取…</p>}
      {rows && rows.length === 0 && <p className="account-note">没有符合条件的任务。</p>}
      {rows && rows.length > 0 && (
        <table className="usage-table">
          <thead>
            <tr><th>时间</th><th>提问</th><th>模型</th><th>用量</th></tr>
          </thead>
          <tbody>
            {rows.map((row, i) => {
              const canJump = !!(row.session_id && row.task_id);
              return (
                <tr
                  key={`${row.task_id ?? ''}-${i}`}
                  className={canJump ? 'jump' : ''}
                  onClick={() => {
                    if (!canJump || !row.session_id || !row.task_id) return;
                    onJump(row.session_id, row.task_id, row.question || '');
                    onClose();
                  }}
                >
                  <td>{formatLedgerTime(row.created_at)}</td>
                  <td>{row.question || (canJump ? '（打开这次提问）' : '找不到对应会话')}</td>
                  <td>{modelDisplayName(row.model ?? undefined)}</td>
                  <td>{formatTokens(row.settle ?? undefined)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Dialog>
  );
}

const PROFILE_FIELDS: { key: keyof MemoryProfile; label: string; hint: string }[] = [
  { key: 'work', label: '工作背景', hint: '岗位、技术栈、正在做的项目。助手会按这些理解你的工作语境。' },
  { key: 'personal', label: '个人背景', hint: '称呼、沟通习惯、你希望助手怎样跟你说话。' },
  { key: 'focus', label: '当前关注', hint: '这阵子最要紧的事。过时了就改掉或清空。' },
  { key: 'history', label: '近期记录', hint: '值得留着的决定和背景，不是每一句对话。' },
];

export function MemoryDialog({ onClose }: { onClose: () => void }) {
  const [profile, setProfile] = useState<MemoryProfile>(EMPTY_PROFILE);
  const [facts, setFacts] = useState<MemoryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [draft, setDraft] = useState('');
  const [editing, setEditing] = useState<number | null>(null);
  const [editText, setEditText] = useState('');

  useEffect(() => {
    let cancelled = false;
    getMemoryBundle()
      .then((bundle) => {
        if (cancelled) return;
        setProfile(bundle.profile);
        setFacts(bundle.memories);
      })
      .catch(() => {
        if (!cancelled) setError('暂时读不到长期记忆');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const saveProfile = async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      setProfile(await saveMemoryProfile(profile));
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog title="长期记忆" wide onClose={onClose}>
      <p className="account-note">
        上面四段是你自己维护的背景，助手每轮都会看到。下面的短条目来自你说的「记住…」，也可以在这里改。
      </p>
      {PROFILE_FIELDS.map((field) => (
        <label key={field.key} className="profile-field">
          <span>{field.label}</span>
          <small>{field.hint}</small>
          <textarea
            rows={4}
            maxLength={2000}
            value={profile[field.key]}
            onChange={(e) => {
              setSaved(false);
              setProfile((prev) => ({ ...prev, [field.key]: e.target.value }));
            }}
          />
        </label>
      ))}
      {error && <p className="account-err">{error}</p>}
      {saved && <p className="account-ok">背景已保存，下一轮对话就会用上。</p>}
      <button type="button" className="send" disabled={saving} onClick={() => void saveProfile()}>
        {saving ? '保存中…' : '保存背景'}
      </button>
      <h3 className="profile-facts-title">记下的条目</h3>
      <form
        className="account-form"
        onSubmit={(e) => {
          e.preventDefault();
          const content = draft.trim();
          if (!content) return;
          void addMemory(content).then((row) => {
            setFacts((rows) => [row, ...(rows ?? [])]);
            setDraft('');
          }).catch((err) => setError((err as Error).message));
        }}
      >
        <label>
          添加一条
          <textarea value={draft} maxLength={300} rows={2} onChange={(e) => setDraft(e.target.value)} />
        </label>
        <button type="submit" className="send" disabled={!draft.trim()}>保存</button>
      </form>
      {facts === null && !error && <p className="account-note">正在读取…</p>}
      {facts && facts.length === 0 && <p className="account-note">还没有短条目。</p>}
      {facts && facts.length > 0 && (
        <ul className="mem-list">
          {facts.map((m) => (
            <li key={m.id} className="mem-item">
              {editing === m.id ? (
                <textarea value={editText} maxLength={300} rows={2} onChange={(e) => setEditText(e.target.value)} />
              ) : (
                <span className="mem-content">{m.content}</span>
              )}
              <span className="mem-meta">
                {m.source === 'user' ? '手动添加' : '助手记录'} · {formatLedgerTime(m.created_at)}
              </span>
              <span className="mem-actions">
                {editing === m.id ? (
                  <button
                    type="button"
                    onClick={() => {
                      void updateMemory(m.id, editText).then((row) => {
                        setFacts((rows) => (rows ?? []).map((item) => (item.id === m.id ? { ...item, content: row.content } : item)));
                        setEditing(null);
                      }).catch((err) => setError((err as Error).message));
                    }}
                  >
                    完成
                  </button>
                ) : (
                  <button type="button" onClick={() => { setEditing(m.id); setEditText(m.content); }}>编辑</button>
                )}
                <button
                  type="button"
                  onClick={() => {
                    void deleteMemory(m.id).then(() => {
                      setFacts((rows) => (rows ?? []).filter((item) => item.id !== m.id));
                    }).catch((err) => setError((err as Error).message));
                  }}
                >
                  删除
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  );
}

export function SettingsDialog({ onClose }: { onClose: () => void }) {
  const [items, setItems] = useState<SettingItem[] | null>(null);
  const [editable, setEditable] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, boolean | number>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState('');
  const [note, setNote] = useState('');

  useEffect(() => {
    let cancelled = false;
    getSettings()
      .then((res) => {
        if (cancelled) return;
        setItems(res.items);
        setEditable(res.editable);
        setDrafts(Object.fromEntries(res.items.map((item) => [item.key, item.value])));
      })
      .catch(() => {
        if (!cancelled) setError('暂时读不到系统设置');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const dirty = (item: SettingItem) => drafts[item.key] !== item.value;

  return (
    <Dialog title="系统设置" wide onClose={onClose}>
      <section className="settings-card">
        <h3>系统 <span>全员生效</span></h3>
        <p className="account-note">
          这两项改的是整个办公助手，不是只改你自己。{editable ? '你是管理员，改完下一次任务就按新值走。' : '只有管理员能改，你可以查看当前值。'}
        </p>
        {error && <p className="account-err">{error}</p>}
        {items === null && !error && <p className="account-note">正在读取…</p>}
        {items?.map((item) => (
          <div key={item.key} className="settings-row">
            <div>
              <strong>{item.label}</strong>
              <p>{item.description}</p>
            </div>
            <div className="settings-control">
              {item.value_type === 'bool' ? (
                <button
                  type="button"
                  className={`settings-toggle${drafts[item.key] ? ' on' : ''}`}
                  aria-pressed={!!drafts[item.key]}
                  disabled={!editable || saving === item.key}
                  onClick={() => setDrafts((prev) => ({ ...prev, [item.key]: !prev[item.key] }))}
                >
                  <i />
                </button>
              ) : (
                <input
                  type="number"
                  min={item.min ?? 0}
                  max={item.max ?? undefined}
                  disabled={!editable || saving === item.key}
                  value={Number(drafts[item.key] ?? item.value)}
                  onChange={(e) => setDrafts((prev) => ({ ...prev, [item.key]: Number(e.target.value) }))}
                />
              )}
              {editable && dirty(item) && (
                <button
                  type="button"
                  className="send"
                  disabled={saving === item.key}
                  onClick={() => {
                    setSaving(item.key);
                    setNote('');
                    void saveSetting(item.key, drafts[item.key])
                      .then((value) => {
                        setItems((prev) => (prev ?? []).map((row) => (row.key === item.key ? { ...row, value } : row)));
                        setDrafts((prev) => ({ ...prev, [item.key]: value }));
                        setNote(`「${item.label}」已保存，下一次任务生效。`);
                      })
                      .catch((e) => setError((e as Error).message))
                      .finally(() => setSaving(''));
                  }}
                >
                  {saving === item.key ? '保存中…' : '确认修改'}
                </button>
              )}
            </div>
          </div>
        ))}
        {note && <p className="account-ok">{note}</p>}
      </section>
      <section className="settings-card">
        <h3>个人 <span>只影响你</span></h3>
        <div className="settings-row">
          <div>
            <strong>当前模型</strong>
            <p>在输入条里切换。记在这个会话上，别人的会话不会跟着变。</p>
          </div>
        </div>
        <div className="settings-row">
          <div>
            <strong>回答力度</strong>
            <p>每次发送前在输入条里选低、高、最大。只作用于你这一次提问。</p>
          </div>
        </div>
        <p className="account-note">目前没有别的个人开关。长期记忆在旁边那一栏，也只属于你自己。</p>
      </section>
    </Dialog>
  );
}

export function PasswordDialog({ onClose }: { onClose: () => void }) {
  const [oldPw, setOldPw] = useState('');
  const [nextPw, setNextPw] = useState('');
  const [again, setAgain] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);

  return (
    <Dialog title="修改密码" onClose={onClose}>
      <form
        className="account-form"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          if (nextPw.length < 8) {
            setError('新密码至少 8 位');
            return;
          }
          if (nextPw !== again) {
            setError('两次输入的新密码不一致');
            return;
          }
          setBusy(true);
          void changePassword(oldPw, nextPw)
            .then(() => {
              setOk(true);
              setOldPw('');
              setNextPw('');
              setAgain('');
            })
            .catch((err) => setError((err as Error).message))
            .finally(() => setBusy(false));
        }}
      >
        <label>
          当前密码
          <input type="password" value={oldPw} autoComplete="current-password" onChange={(e) => setOldPw(e.target.value)} />
        </label>
        <label>
          新密码
          <input type="password" value={nextPw} autoComplete="new-password" onChange={(e) => setNextPw(e.target.value)} />
        </label>
        <label>
          再输入一次
          <input type="password" value={again} autoComplete="new-password" onChange={(e) => setAgain(e.target.value)} />
        </label>
        {error && <p className="account-err">{error}</p>}
        {ok && <p className="account-ok">密码已更新，其他设备上的旧登录会失效。</p>}
        <button type="submit" className="send" disabled={busy || !oldPw || !nextPw || !again}>
          {busy ? '保存中…' : '保存'}
        </button>
      </form>
    </Dialog>
  );
}
