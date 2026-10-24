// 工作台：侧栏 + 聊天流 + 底部 PromptBar（发送 / 停止 / 上传 / 模型）。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Attachment01Icon } from '@hugeicons/core-free-icons';

import AppSidebar, { type SessionMeta, type SessionUser } from '../components/AppSidebar';
import ChatMessage, { type ChatMessageData } from '../components/ChatMessage';
import FilePreview from '../components/FilePreview';
import PromptBar, { type PromptBarModel } from '../components/bits/PromptBar';
import { sortDialogueModels, toPromptModel, type DialogueModel } from '../components/ModelPicker';
import { useNdjsonStream } from '../hooks/useNdjsonStream';
import type { StreamEvent } from '../types';
import ContextRing from '../components/ContextRing';
import { deriveContextUsage, deriveCurrentAgent, agentLabel, pauseText } from '../lib/derive';
import { authHeaders, clearToken, createSession, deleteSession, getMessages, getQuota, latestPausedTask, listSessions, pauseTask, updateSession } from '../lib/api';

const EFFORTS = ['低', '高', '最大'] as const;
const EFFORT_API: Record<string, string> = { 低: 'low', 高: 'high', 最大: 'max' };

const SOURCES = [
  {
    key: 'files',
    name: '上传文档',
    description: '.md / .txt / .json / .csv / .docx / .xlsx / .pdf / 图片，不超过 10MB',
    icon: Attachment01Icon,
    attach: true,
  },
];

function basename(path: string): string {
  return path.split('/').pop() || path;
}

function messageAnchor(list: ChatMessageData[], index: number): string | undefined {
  const current = list[index];
  if (!current || current.role !== 'user') return undefined;
  const next = list[index + 1];
  const runId = next?.role === 'assistant' ? next.events?.find((event) => event.run_id)?.run_id : undefined;
  return runId ? `q-${runId}` : `msg-${index}`;
}

function parseCreatedAt(raw: string | undefined): number | undefined {
  if (!raw) return undefined;
  const n = Date.parse(raw);
  return Number.isFinite(n) ? n : undefined;
}

export function WorkspacePage({ user, onLogout, onOpenAdmin }: { user: SessionUser; onLogout: () => void; onOpenAdmin?: () => void }) {
  const { events, status, error, start, stop, reset } = useNdjsonStream('/api/v1/demo/stream');
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [currentId, setCurrentId] = useState<string>('');
  const [messages, setMessages] = useState<ChatMessageData[]>([]);
  const [balance, setBalance] = useState<number | null>(null);
  const [paused, setPaused] = useState<{ taskId: string; message: string } | null>(null);
  const [usage, setUsage] = useState<{ month_tokens: number; month_count: number; total_tokens: number; total_count: number } | null>(null);
  const [modelId, setModelId] = useState(() => localStorage.getItem('office_model') || 'deepseek-chat');
  const [locate, setLocate] = useState<{ taskId: string; question: string } | null>(null);
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [models, setModels] = useState<DialogueModel[]>([]);
  const [incoming, setIncoming] = useState<{ id: number; files: string[] } | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const sealedRef = useRef(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const fileWait = useRef<((file: File | null) => void) | null>(null);
  const pathByLabel = useRef(new Map<string, string>());
  const currentIdRef = useRef(currentId);
  currentIdRef.current = currentId;

  const refreshQuota = useCallback(() => {
    getQuota()
      .then((q) => {
        setBalance(q.balance);
        setUsage(q.usage ?? null);
      })
      .catch(() => {});
  }, []);

  const ensureSession = useCallback(async (): Promise<string> => {
    if (currentIdRef.current) return currentIdRef.current;
    const sid = await createSession();
    setCurrentId(sid);
    currentIdRef.current = sid;
    setSessions((prev) => [{ id: sid, title: '新会话', updatedAt: Date.now() }, ...prev]);
    return sid;
  }, []);

  const remember = useCallback((path: string): string => {
    const base = basename(path);
    const taken = pathByLabel.current.get(base);
    const label = taken && taken !== path ? path : base;
    pathByLabel.current.set(label, path);
    return label;
  }, []);

  const uploadFile = useCallback(async (file: File): Promise<string | null> => {
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await fetch('/api/v1/documents', {
        method: 'POST',
        headers: authHeaders(),
        body: fd,
      });
      if (res.status === 401) {
        clearToken();
        onLogout();
        return null;
      }
      const data = await res.json();
      if (!res.ok) {
        setUploadError(`上传失败：${data?.detail?.message ?? `HTTP ${res.status}`}`);
        setTimeout(() => setUploadError(null), 5000);
        return null;
      }
      return String(data.file_name);
    } catch (e) {
      setUploadError(`上传失败：${(e as Error).message}`);
      setTimeout(() => setUploadError(null), 5000);
      return null;
    }
  }, [onLogout]);

  useEffect(() => {
    fetch('/api/v1/models')
      .then((r) => r.json())
      .then((d) => setModels(d.models ?? []))
      .catch(() => setModels([]));
  }, []);

  useEffect(() => {
    (async () => {
      refreshQuota();
      try {
        const list = await listSessions();
        if (!list.length) {
          const sid = await createSession();
          setCurrentId(sid);
          setSessions([{ id: sid, title: '新会话', updatedAt: Date.now() }]);
          return;
        }
        setSessions(list.map((s) => ({ id: s.session_id, title: s.title, pinned: !!s.pinned, updatedAt: new Date(s.updated_at).getTime() || Date.now() })));
        setCurrentId(list[0].session_id);
        await selectSession(list[0].session_id);
      } catch (e) {
        if ((e as Error).message === 'UNAUTHORIZED') onLogout();
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectSession = useCallback(async (sid: string) => {
    if (status === 'streaming') stop();
    sealedRef.current = true;
    reset();
    setCurrentId(sid);
    setMessages([]);
    try {
      const msgs = await getMessages(sid);
      setMessages(
        msgs.map((m) => {
          const createdAt = parseCreatedAt(m.created_at);
          if (m.role === 'user') {
            let paths: string[] | undefined;
            if (m.trace) {
              try {
                const parsed = JSON.parse(m.trace) as { attachments?: string[] };
                paths = parsed.attachments;
              } catch {
                paths = undefined;
              }
            }
            return {
              role: 'user' as const,
              text: m.content,
              attachments: paths?.map(basename),
              attachmentPaths: paths,
              createdAt,
            };
          }
          let evs: StreamEvent[] | undefined;
          if (m.trace) {
            try {
              evs = JSON.parse(m.trace) as StreamEvent[];
            } catch {
              evs = undefined;
            }
          }
            return evs
            ? { role: 'assistant' as const, events: evs, streaming: false, createdAt, model: m.model ?? undefined, tokens: m.tokens ?? undefined }
            : { role: 'assistant' as const, content: m.content, createdAt, model: m.model ?? undefined, tokens: m.tokens ?? undefined };
        }),
      );
    } catch (e) {
      if ((e as Error).message === 'UNAUTHORIZED') onLogout();
    }
    // p7.1：刷新/切会话后，若本会话有"暂停/失败"的任务，横幅提示可继续
    try {
      const t = await latestPausedTask(sid);
      setPaused(t ? { taskId: t.id, message: pauseText(String(t.status), (t.pause_payload as Record<string, unknown>) ?? {}) } : null);
    } catch {
      setPaused(null);
    }
  }, [status, stop, reset, onLogout]);

  useEffect(() => {
    if ((status === 'done' || status === 'error') && events.length && !sealedRef.current) {
      sealedRef.current = true;
      // p7.1：暂停/失败也要把本轮事件固化，并在横幅里给出"继续/重试"入口
      const done = [...events].reverse().find((e) => e.type === 'done');
      const doneStatus = String(done?.data?.status ?? '');
      if (doneStatus.startsWith('paused') || doneStatus === 'failed') {
        const quota = [...events].reverse().find((e) => e.type === 'quota_paused');
        const payload = (quota?.data ?? done?.data ?? {}) as Record<string, unknown>;
        setPaused({ taskId: done?.run_id ?? '', message: pauseText(doneStatus, payload) });
      } else {
        setPaused(null);
      }
      setMessages((prev) => [...prev, { role: 'assistant', events, streaming: false, createdAt: Date.now() }]);
      if (status === 'done') {
        listSessions()
          .then((list) => setSessions(list.map((s) => ({ id: s.session_id, title: s.title, pinned: !!s.pinned, updatedAt: new Date(s.updated_at).getTime() || Date.now() }))))
          .catch(() => {});
        refreshQuota();
      }
      reset();
    }
  }, [status, events, reset, refreshQuota]);

  /** p7.1：暂停——先通知后端（协作式取消），再断本地流；横幅给出继续入口。 */
  const onPauseClick = () => {
    const id = events.find((e) => e.run_id)?.run_id ?? '';
    if (id) {
      void pauseTask(id).then((ok) => {
        if (ok) setPaused({ taskId: id, message: '任务已按你的要求暂停，可点「继续」重跑' });
      });
    }
    stop();
  };

  /** p7.1：继续/重试——按原任务重跑，后端新任务 retry_of 指回原任务。 */
  const onResume = () => {
    if (!paused?.taskId) return;
    const taskId = paused.taskId;
    setPaused(null);
    sealedRef.current = false;
    void start({
      url: `/api/v1/tasks/${encodeURIComponent(taskId)}/resume`,
      method: 'POST',
      headers: authHeaders(),
      on401: () => {
        clearToken();
        onLogout();
      },
    });
  };

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages.length, events.length, status]);

  const dispatchTask = async (text: string, paths: string[], modelId?: string, force = false, effort?: string) => {
    const trimmed = text.trim();
    if ((!trimmed && paths.length === 0) || (status === 'streaming' && !force)) return;
    sealedRef.current = false;
    setPaused(null); // 新任务发出 → 收起上一次的暂停横幅
    try {
      const sid = await ensureSession();
      setMessages((prev) => [
        ...prev,
        {
          role: 'user',
          text: trimmed,
          attachments: paths.length ? paths.map(basename) : undefined,
          attachmentPaths: paths.length ? paths : undefined,
          createdAt: Date.now(),
        },
      ]);
      const model = modelId || localStorage.getItem('office_model') || undefined;
      void start({
        url: '/api/v1/tasks',
        method: 'POST',
        body: {
          text: trimmed,
          session_id: sid,
          model,
          ...(effort ? { effort } : {}),
          ...(paths.length ? { attachments: paths } : {}),
        },
        headers: authHeaders(),
        on401: () => {
          clearToken();
          onLogout();
        },
      });
    } catch (e) {
      if ((e as Error).message === 'UNAUTHORIZED') onLogout();
    }
  };

  const onModelChange = async (m: PromptBarModel) => {
    localStorage.setItem('office_model', m.key);
    setModelId(m.key);
    const sid = currentIdRef.current;
    if (!sid) return;
    try {
      await fetch(`/api/v1/sessions/${encodeURIComponent(sid)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ model: m.key }),
      });
    } catch {
      /* 模型偏好已在 localStorage，下次请求仍会带上 */
    }
  };

  const pickFile = () =>
    new Promise<File | null>((resolve) => {
      const input = fileRef.current;
      if (!input) {
        resolve(null);
        return;
      }
      let settled = false;
      const finish = (file: File | null) => {
        if (settled) return;
        settled = true;
        fileWait.current = null;
        input.removeEventListener('cancel', onCancel);
        resolve(file);
      };
      const onCancel = () => finish(null);
      fileWait.current = finish;
      input.addEventListener('cancel', onCancel, { once: true });
      input.click();
    });

  const onAttach = async () => {
    const file = await pickFile();
    if (!file) return;
    const path = await uploadFile(file);
    if (!path) return;
    return remember(path);
  };

  const onDropFiles = async (files: FileList) => {
    const labels: string[] = [];
    for (const file of Array.from(files)) {
      const path = await uploadFile(file);
      if (path) labels.push(remember(path));
    }
    if (labels.length) setIncoming({ id: Date.now(), files: labels });
  };

  const onEditSubmit = async (index: number, text: string, paths: string[]): Promise<boolean> => {
    if (status === 'streaming') {
      sealedRef.current = true;
      stop();
      reset();
    }
    const sid = currentIdRef.current;
    if (sid) {
      const res = await fetch(`/api/v1/sessions/${encodeURIComponent(sid)}/rewind`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ keep: index }),
      });
      if (res.status === 401) {
        clearToken();
        onLogout();
        return false;
      }
      if (!res.ok) {
        setUploadError('无法从这条消息重新开始，请稍后再试');
        setTimeout(() => setUploadError(null), 5000);
        return false;
      }
    }
    setMessages((prev) => prev.slice(0, index));
    await dispatchTask(text, paths, localStorage.getItem('office_model') || undefined, true);
    return true;
  };

  const placePinned = (list: SessionMeta[]) => [
    ...list.filter((s) => s.pinned),
    ...list.filter((s) => !s.pinned),
  ];

  const onRenameSession = async (id: string, title: string) => {
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title } : s)));
    try {
      await updateSession(id, { title });
    } catch (e) {
      if ((e as Error).message === 'UNAUTHORIZED') onLogout();
    }
  };

  const onPinSession = async (id: string, pinned: boolean) => {
    setSessions((prev) => placePinned(prev.map((s) => (s.id === id ? { ...s, pinned } : s))));
    try {
      await updateSession(id, { pinned });
    } catch (e) {
      if ((e as Error).message === 'UNAUTHORIZED') onLogout();
    }
  };

  const onDeleteSession = async (id: string) => {
    const rest = sessions.filter((s) => s.id !== id);
    setSessions(rest);
    try {
      await deleteSession(id);
    } catch (e) {
      if ((e as Error).message === 'UNAUTHORIZED') onLogout();
      return;
    }
    if (currentId !== id) return;
    if (rest[0]) {
      await selectSession(rest[0].id);
      return;
    }
    await newChat();
  };

  const newChat = async () => {
    if (status === 'streaming') stop();
    sealedRef.current = true;
    reset();
    setMessages([]);
    try {
      const sid = await createSession();
      setCurrentId(sid);
      setSessions((prev) => [{ id: sid, title: '新会话', updatedAt: Date.now() }, ...prev]);
    } catch (e) {
      if ((e as Error).message === 'UNAUTHORIZED') onLogout();
    }
  };

  const liveMessages = useMemo<ChatMessageData[]>(
    () => (events.length || status === 'streaming'
      ? [...messages, { role: 'assistant', events, streaming: status === 'streaming' }]
      : messages),
    [messages, events, status],
  );

  const promptModels = useMemo(() => sortDialogueModels(models).map(toPromptModel), [models]);
  const modelWindow = models.find((m) => m.id === modelId)?.context_window
    || models.find((m) => m.id === 'deepseek-chat')?.context_window
    || 0;

  useEffect(() => {
    if (!locate) return undefined;
    const byTask = document.getElementById(`q-${locate.taskId}`);
    const byText = locate.question
      ? scrollRef.current?.querySelector<HTMLElement>(`[data-question="${CSS.escape(locate.question)}"]`)
      : null;
    const el = byTask || byText || null;
    if (!el) return undefined;
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    const timer = window.setTimeout(() => setLocate(null), 2600);
    return () => window.clearTimeout(timer);
  }, [locate, messages]);
  const currentAgent = deriveCurrentAgent(events);
  const contextUsage = useMemo(() => {
    const live = events.length ? deriveContextUsage(events) : null;
    if (live) return live;
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const found = messages[i].events ? deriveContextUsage(messages[i].events!) : null;
      if (found) return found;
    }
    return null;
  }, [events, messages]);

  return (
    <div className="app-shell">
      <AppSidebar
        sessions={sessions}
        currentId={currentId}
        onSelect={(id) => void selectSession(id)}
        onNew={() => void newChat()}
        onRename={(id, title) => void onRenameSession(id, title)}
        onPin={(id, pinned) => void onPinSession(id, pinned)}
        onDelete={(id) => void onDeleteSession(id)}
        user={user}
        balance={balance}
        usage={usage}
        models={models}
        onJumpToTask={(sessionId, taskId, question) => {
          setLocate({ taskId, question });
          if (currentIdRef.current !== sessionId) void selectSession(sessionId);
        }}
        onLogout={() => {
          if (status === 'streaming') stop();
          onLogout();
        }}
        onOpenAdmin={onOpenAdmin}
      />
      <main className="chat-main">
        <header className="chat-header">
          <h2>{sessions.find((s) => s.id === currentId)?.title ?? '新会话'}</h2>
          <div className="header-side">
            {currentAgent && (
              <span className="agent-now">
                当前回答：<span className="badge agent">{agentLabel(currentAgent.agent)}</span>
              </span>
            )}
            <ContextRing usage={contextUsage} windowSize={modelWindow} />
          </div>
        </header>
        <div className="message-scroll" ref={scrollRef}>
          {liveMessages.length === 0 && (
            <div className="welcome">
              <h3>有什么可以帮你？</h3>
              <p>试试：帮我查一下公司的年假制度</p>
            </div>
          )}
          {liveMessages.map((m, i) => (
            <ChatMessage
              key={i}
              index={i}
              msg={m}
              anchorId={messageAnchor(liveMessages, i)}
              located={!!locate && messageAnchor(liveMessages, i) === `q-${locate.taskId}`}
              onEditSubmit={(idx, text, paths) => void onEditSubmit(idx, text, paths)}
              onPreview={setPreviewPath}
            />
          ))}
        </div>
        {uploadError && <div className="banner warn">{uploadError}</div>}
        {error && <div className="banner err">{error}</div>}
        {paused && (
          <div className="banner warn pause-banner">
            <span>⏸ {paused.message}</span>
            <span className="pause-actions">
              <button type="button" className="admin-btn" onClick={onResume} disabled={status === 'streaming'}>
                继续
              </button>
              <button type="button" className="admin-btn ghost" onClick={() => setPaused(null)}>
                暂不
              </button>
            </span>
          </div>
        )}
        <div
          className={`composer-wrap${dragOver ? ' drag' : ''}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            if (e.dataTransfer.files?.length) void onDropFiles(e.dataTransfer.files);
          }}
        >
          <PromptBar
            placeholder="输入任务，回车发送…（可拖拽文件上传）"
            sources={SOURCES}
            commands={[]}
            models={promptModels}
            defaultModel={modelId}
            efforts={[...EFFORTS]}
            defaultEffort="高"
            busy={status === 'streaming'}
            onOpenFile={(label) => setPreviewPath(pathByLabel.current.get(label) ?? label)}
            onSend={(text, detail) => {
              const paths = detail.attachments.map((label) => pathByLabel.current.get(label) ?? label);
              const effort = detail.effort ? EFFORT_API[detail.effort] : undefined;
              void dispatchTask(text, paths, detail.model?.key, false, effort);
            }}
            onStop={onPauseClick}
            onAttach={onAttach}
            onModelChange={(m) => void onModelChange(m)}
            incoming={incoming}
            background="#1a1f27"
            color="#e6e9ef"
            menuBackground="#222834"
            sparkColor="#58a6ff"
            width={1200}
            radius={16}
            maxRows={5}
          />
          <input
            ref={fileRef}
            type="file"
            accept=".md,.txt,.json,.csv,.docx,.xlsx,.pdf"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0] ?? null;
              e.target.value = '';
              fileWait.current?.(file);
            }}
          />
        </div>
        {previewPath && <FilePreview path={previewPath} onClose={() => setPreviewPath(null)} />}
      </main>
    </div>
  );
}

export default WorkspacePage;
