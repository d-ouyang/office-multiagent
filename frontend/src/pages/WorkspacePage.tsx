// 工作台：侧栏 + 聊天流 + 底部 PromptBar（发送 / 停止 / 上传 / 模型）。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Attachment01Icon } from '@hugeicons/core-free-icons';

import AppSidebar, { type SessionMeta, type SessionUser } from '../components/AppSidebar';
import ChatMessage, { type ChatMessageData } from '../components/ChatMessage';
import FilePreview from '../components/FilePreview';
import PromptBar, { type PromptBarModel } from '../components/bits/PromptBar';
import { toPromptModel, type DialogueModel } from '../components/ModelPicker';
import { useNdjsonStream } from '../hooks/useNdjsonStream';
import type { StreamEvent } from '../types';
import { deriveCurrentAgent, agentLabel } from '../lib/derive';
import { authHeaders, clearToken, createSession, getMessages, getQuota, listSessions } from '../lib/api';

const EFFORTS = ['低', '高', '最大'] as const;
const EFFORT_API: Record<string, string> = { 低: 'low', 高: 'high', 最大: 'max' };

const SOURCES = [
  {
    key: 'files',
    name: '上传文档',
    description: '.md / .txt / .pdf，不超过 10MB',
    icon: Attachment01Icon,
    attach: true,
  },
];

function basename(path: string): string {
  return path.split('/').pop() || path;
}

function parseCreatedAt(raw: string | undefined): number | undefined {
  if (!raw) return undefined;
  const n = Date.parse(raw);
  return Number.isFinite(n) ? n : undefined;
}

export function WorkspacePage({ user, onLogout }: { user: SessionUser; onLogout: () => void }) {
  const { events, status, error, start, stop, reset } = useNdjsonStream('/api/v1/demo/stream');
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [currentId, setCurrentId] = useState<string>('');
  const [messages, setMessages] = useState<ChatMessageData[]>([]);
  const [balance, setBalance] = useState<number | null>(null);
  const [usage, setUsage] = useState<{ month_tokens: number; month_count: number; total_tokens: number; total_count: number } | null>(null);
  const [modelName, setModelName] = useState('DeepSeek V3');
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
        setSessions(list.map((s) => ({ id: s.session_id, title: s.title, updatedAt: new Date(s.updated_at).getTime() || Date.now() })));
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
  }, [status, stop, reset, onLogout]);

  useEffect(() => {
    if ((status === 'done' || status === 'error') && events.length && !sealedRef.current) {
      sealedRef.current = true;
      setMessages((prev) => [...prev, { role: 'assistant', events, streaming: false, createdAt: Date.now() }]);
      if (status === 'done') {
        listSessions()
          .then((list) => setSessions(list.map((s) => ({ id: s.session_id, title: s.title, updatedAt: new Date(s.updated_at).getTime() || Date.now() }))))
          .catch(() => {});
        refreshQuota();
      }
      reset();
    }
  }, [status, events, reset, refreshQuota]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages.length, events.length, status]);

  const dispatchTask = async (text: string, paths: string[], modelId?: string, force = false, effort?: string) => {
    const trimmed = text.trim();
    if ((!trimmed && paths.length === 0) || (status === 'streaming' && !force)) return;
    sealedRef.current = false;
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
    setModelName(m.name);
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

  const promptModels = useMemo(() => models.map(toPromptModel), [models]);
  const defaultModel = localStorage.getItem('office_model') || 'deepseek-chat';
  const currentAgent = deriveCurrentAgent(events);

  return (
    <div className="app-shell">
      <AppSidebar
        sessions={sessions}
        currentId={currentId}
        onSelect={(id) => void selectSession(id)}
        onNew={() => void newChat()}
        user={user}
        balance={balance}
        usage={usage}
        modelName={modelName}
        onLogout={() => {
          if (status === 'streaming') stop();
          onLogout();
        }}
      />
      <main className="chat-main">
        <header className="chat-header">
          <h2>{sessions.find((s) => s.id === currentId)?.title ?? '新会话'}</h2>
          {currentAgent && (
            <span className="agent-now">
              当前回答：<span className="badge agent">{agentLabel(currentAgent.agent)}</span>
            </span>
          )}
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
              onEditSubmit={(idx, text, paths) => void onEditSubmit(idx, text, paths)}
              onPreview={setPreviewPath}
            />
          ))}
        </div>
        {uploadError && <div className="banner warn">{uploadError}</div>}
        {error && <div className="banner err">{error}</div>}
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
            defaultModel={defaultModel}
            efforts={[...EFFORTS]}
            defaultEffort="高"
            busy={status === 'streaming'}
            onOpenFile={(label) => setPreviewPath(pathByLabel.current.get(label) ?? label)}
            onSend={(text, detail) => {
              const paths = detail.attachments.map((label) => pathByLabel.current.get(label) ?? label);
              const effort = detail.effort ? EFFORT_API[detail.effort] : undefined;
              void dispatchTask(text, paths, detail.model?.key, false, effort);
            }}
            onStop={stop}
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
            accept=".md,.txt,.pdf"
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
