// 工作台（p6.2a/p6.2c）：参考 RAG ChatView 布局 —— 侧栏(会话/用户) + 聊天流 + 底部输入条(模型切换)。
// p6.2c：会话接真后端（创建/列表/历史/落库）；当前进行中的流式回答本地实时渲染，done 后已由后端落库。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import AppSidebar, { type SessionMeta, type SessionUser } from '../components/AppSidebar';
import ChatMessage, { type ChatMessageData } from '../components/ChatMessage';
import ModelPicker from '../components/ModelPicker';
import { useNdjsonStream } from '../hooks/useNdjsonStream';
import type { StreamEvent } from '../types';
import { deriveCurrentAgent, agentLabel } from '../lib/derive';
import { authHeaders, clearToken, createSession, getMessages, getQuota, listSessions } from '../lib/api';

export function WorkspacePage({ user, onLogout }: { user: SessionUser; onLogout: () => void }) {
  const { events, status, error, start, stop, reset } = useNdjsonStream('/api/v1/demo/stream');
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [currentId, setCurrentId] = useState<string>('');
  const [messages, setMessages] = useState<ChatMessageData[]>([]);
  const [balance, setBalance] = useState<number | null>(null);
  const [uploaded, setUploaded] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);
  const sealedRef = useRef(false);

  const refreshQuota = useCallback(() => {
    getQuota()
      .then((q) => setBalance(q.balance))
      .catch(() => {});
  }, []);

  const ensureSession = useCallback(async (): Promise<string> => {
    if (currentId) return currentId;
    const sid = await createSession();
    setCurrentId(sid);
    setSessions((prev) => [{ id: sid, title: '新会话', updatedAt: Date.now() }, ...prev]);
    return sid;
  }, [currentId]);

  // 初始加载会话列表；无会话则先建一个（避免用户第一句话才建）
  useEffect(() => {
    (async () => {
      refreshQuota(); // p6.4：侧栏余额
      try {
        const list = await listSessions();
        if (!list.length) {
          const sid = await createSession();
          setCurrentId(sid);
          setSessions([{ id: sid, title: '新会话', updatedAt: Date.now() }]);
          return;
        }
        setSessions(list.map((s) => ({ id: s.session_id, title: s.title, updatedAt: Date.now() })));
        setCurrentId(list[0].session_id);
        await selectSession(list[0].session_id); // p6.7：初始也加载最近会话的历史+过程
      } catch (e) {
        if ((e as Error).message === 'UNAUTHORIZED') onLogout();
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 切换会话：拉历史消息（p6.7：assistant 消息带 trace 过程事件，重建完整渲染）
  const selectSession = useCallback(async (sid: string) => {
    if (status === 'streaming') stop();
    sealedRef.current = true; // 切走不固化当前流（后端已按 session 落库）
    reset();
    setCurrentId(sid);
    setMessages([]);
    try {
      const msgs = await getMessages(sid);
      setMessages(
        msgs.map((m) => {
          if (m.role === 'user') return { role: 'user' as const, text: m.content };
          let events: StreamEvent[] | undefined;
          if (m.trace) {
            try {
              events = JSON.parse(m.trace) as StreamEvent[];
            } catch {
              events = undefined;
            }
          }
          return events
            ? { role: 'assistant' as const, events, streaming: false }
            : { role: 'assistant' as const, content: m.content };
        }),
      );
    } catch (e) {
      if ((e as Error).message === 'UNAUTHORIZED') onLogout();
    }
  }, [status, stop, reset, onLogout]);

  // 流结束 → 当前流已由后端落库；刷新列表标题 + 余额（p6.4）即可，本地不再固化（防重复）
  useEffect(() => {
    if (status === 'done' && events.length && !sealedRef.current) {
      sealedRef.current = true;
      listSessions()
        .then((list) => setSessions(list.map((s) => ({ id: s.session_id, title: s.title, updatedAt: Date.now() }))))
        .catch(() => {});
      refreshQuota();
      reset();
    }
  }, [status, events, reset, refreshQuota]);

  // 自动滚底
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages.length, events.length, status]);

  const sendTask = async () => {
    const text = input.trim();
    if (!text || status === 'streaming') return;
    sealedRef.current = false;
    setInput('');
    try {
      const sid = await ensureSession();
      setMessages((prev) => [...prev, { role: 'user', text }]);
      const model = localStorage.getItem('office_model') || undefined; // p6.5：请求级模型
      void start({
        url: '/api/v1/tasks',
        method: 'POST',
        body: { text, session_id: sid, model },
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

  // p6.5：切换模型 → 更新当前会话默认模型（后端按会话默认执行）
  const onModelChange = async (modelId: string) => {
    if (!currentId) return;
    try {
      await fetch(`/api/v1/sessions/${encodeURIComponent(currentId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ model: modelId || null }),
      });
    } catch {
      /* 静默：模型偏好已在 localStorage，下次请求仍按它带 */
    }
  };

  // p6.6：上传文档到自己的目录（供 read_document 读取）
  const onUpload = async (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await fetch('/api/v1/documents', {
        method: 'POST',
        headers: authHeaders(), // 不要设 Content-Type：浏览器自动带 multipart boundary
        body: fd,
      });
      if (res.status === 401) {
        clearToken();
        onLogout();
        return;
      }
      const data = await res.json();
      if (res.ok) {
        setUploaded(String(data.file_name));
        setTimeout(() => setUploaded(null), 5000);
      } else {
        setUploaded(`上传失败：${data?.detail?.message ?? `HTTP ${res.status}`}`);
        setTimeout(() => setUploaded(null), 5000);
      }
    } catch (e) {
      setUploaded(`上传失败：${(e as Error).message}`);
      setTimeout(() => setUploaded(null), 5000);
    }
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

  const currentAgent = deriveCurrentAgent(events);
  const quotaPaused = events.some((e) => e.type === 'quota_paused');

  return (
    <div className="app-shell">
      <AppSidebar
        sessions={sessions}
        currentId={currentId}
        onSelect={(id) => void selectSession(id)}
        onNew={() => void newChat()}
        user={user}
        balance={balance}
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
            <ChatMessage key={i} msg={m} />
          ))}
        </div>
        {quotaPaused && (
          <div className="banner warn">
            token 余额不足，任务已暂停（充值后自动继续，或联系管理员）。
          </div>
        )}
        {uploaded && <div className="banner ok">已上传：{uploaded} —— 可以直接让我读取它</div>}
        {error && <div className="banner err">{error}</div>}
        <footer className="input-bar">
          <ModelPicker onChange={(m) => void onModelChange(m)} />
          <label className="upload-btn" title="上传文档（.md/.txt/.pdf，≤10MB）">
            📎
            <input
              type="file"
              accept=".md,.txt,.pdf"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void onUpload(f);
                e.target.value = '';
              }}
            />
          </label>
          <input
            className="task-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入任务，回车发送…"
            onKeyDown={(e) => e.key === 'Enter' && sendTask()}
            disabled={status === 'streaming'}
          />
          <button className="send" onClick={() => void sendTask()} disabled={status === 'streaming' || !input.trim()}>
            发送
          </button>
          {status === 'streaming' && (
            <button className="ghost" onClick={stop}>
              停止
            </button>
          )}
        </footer>
      </main>
    </div>
  );
}

export default WorkspacePage;
