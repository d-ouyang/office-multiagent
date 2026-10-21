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
  const [ledger, setLedger] = useState<Array<Record<string, unknown>>>([]);
  const [attachments, setAttachments] = useState<Array<{ name: string; path: string }>>([]); // p6.12：随消息附件 chip
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [modelInfo, setModelInfo] = useState<{ id: string; description: string; context_window: number } | null>(null);
  const [input, setInput] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);
  const sealedRef = useRef(false);

  const refreshQuota = useCallback(() => {
    getQuota()
      .then((q) => {
        setBalance(q.balance);
        setLedger(q.ledger as Array<Record<string, unknown>>);
      })
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
        // p6.12：updatedAt=后端最后活跃时间（最后一次问答），侧栏相对时间不再全是加载时刻
        setSessions(list.map((s) => ({ id: s.session_id, title: s.title, updatedAt: new Date(s.updated_at).getTime() || Date.now() })));
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
          if (m.role === 'user') {
            // p6.12：user 消息 trace 存附件列表（{"attachments":["dev/a.md"]}）——历史重建附件 chip
            let atts: string[] | undefined;
            if (m.trace) {
              try {
                const parsed = JSON.parse(m.trace) as { attachments?: string[] };
                atts = parsed.attachments?.map((p) => p.split('/')[1] ?? p);
              } catch {
                atts = undefined; // 非 JSON trace（旧数据）忽略
              }
            }
            return { role: 'user' as const, text: m.content, attachments: atts };
          }
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

  // 流结束/中断 → 把当前流固化进本地消息（后端已按 session 落库，trace 刷新可回读）。
  // ⚠️ p6.7b 修：此前 done 时只 reset() 未固化——正文从界面瞬间消失，刷新后才回来。
  useEffect(() => {
    if ((status === 'done' || status === 'error') && events.length && !sealedRef.current) {
      sealedRef.current = true;
      setMessages((prev) => [...prev, { role: 'assistant', events, streaming: false }]);
      if (status === 'done') {
        listSessions()
          .then((list) => setSessions(list.map((s) => ({ id: s.session_id, title: s.title, updatedAt: new Date(s.updated_at).getTime() || Date.now() }))))
          .catch(() => {});
        refreshQuota();
      }
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
    const atts = attachments; // p6.12：随消息发出并清空 chip
    setAttachments([]);
    try {
      const sid = await ensureSession();
      setMessages((prev) => [
        ...prev,
        { role: 'user', text, attachments: atts.length ? atts.map((a) => a.name) : undefined },
      ]);
      const model = localStorage.getItem('office_model') || undefined; // p6.5：请求级模型
      void start({
        url: '/api/v1/tasks',
        method: 'POST',
        body: {
          text,
          session_id: sid,
          model,
          ...(atts.length ? { attachments: atts.map((a) => a.path) } : {}),
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

  // p6.5/p6.8：切换模型 → 更新当前会话默认模型 + 信息条
  const onModelChange = async (m: { id: string; description: string; context_window: number } | null) => {
    setModelInfo(m);
    if (!currentId) return;
    try {
      await fetch(`/api/v1/sessions/${encodeURIComponent(currentId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ model: m?.id || null }),
      });
    } catch {
      /* 静默：模型偏好已在 localStorage，下次请求仍按它带 */
    }
  };

  // p6.6/p6.12：上传文档到自己的目录（供 read_document 读取）；成功进附件 chip，失败 banner 提示
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
        const path = String(data.file_name);
        setAttachments((prev) => [...prev.filter((a) => a.path !== path), { name: path.split('/')[1] ?? path, path }]);
      } else {
        setUploadError(`上传失败：${data?.detail?.message ?? `HTTP ${res.status}`}`);
        setTimeout(() => setUploadError(null), 5000);
      }
    } catch (e) {
      setUploadError(`上传失败：${(e as Error).message}`);
      setTimeout(() => setUploadError(null), 5000);
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
        ledger={ledger}
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
              msg={m}
              onEdit={(t) => setInput(t)} // p6.10：编辑用户消息 → 回填输入框
            />
          ))}
        </div>
        {quotaPaused && (
          <div className="banner warn">
            token 余额不足，任务已暂停（充值后自动继续，或联系管理员）。
          </div>
        )}
        {uploadError && <div className="banner warn">{uploadError}</div>}
        {attachments.length > 0 && (
          <div className="attach-row">
            {attachments.map((a) => (
              <span key={a.path} className="attach-chip" title={a.path}>
                📎 {a.name}
                <button
                  className="attach-remove"
                  title="移除附件"
                  onClick={() => setAttachments((prev) => prev.filter((x) => x.path !== a.path))}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
        {modelInfo && (
          <div className="model-info" title={modelInfo.description}>
            当前模型：{modelInfo.id} · 上下文 {modelInfo.context_window >= 1_000_000 ? `${Math.round(modelInfo.context_window / 1_000_000)}M` : `${Math.round(modelInfo.context_window / 1000)}K`} —— {modelInfo.description}
          </div>
        )}
        {error && <div className="banner err">{error}</div>}
        <footer
          className="input-bar"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const f = e.dataTransfer.files?.[0];
            if (f) void onUpload(f);
          }}
        >
          <ModelPicker onChange={(m) => void onModelChange(m)} />
          <label className="upload-btn" title="上传文档（.md/.txt/.pdf，≤10MB），也可直接拖拽文件到输入条">
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
            placeholder="输入任务，回车发送…（可拖拽文件上传）"
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
