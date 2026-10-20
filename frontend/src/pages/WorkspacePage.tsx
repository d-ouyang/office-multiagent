// 工作台（p6.2）：参考 RAG ChatView 布局 —— 侧栏(会话/用户) + 聊天流 + 底部输入条(模型切换)。
// 会话本轮为本地多会话；后端会话持久化 API 是 p6.2b。
import { useEffect, useMemo, useRef, useState } from 'react';

import AppSidebar, { type SessionMeta, type SessionUser } from '../components/AppSidebar';
import ChatMessage, { type ChatMessageData } from '../components/ChatMessage';
import ModelPicker from '../components/ModelPicker';
import { useNdjsonStream } from '../hooks/useNdjsonStream';
import { deriveCurrentAgent, agentLabel } from '../lib/derive';
import { authHeaders, clearToken } from '../lib/api';

const newSession = (): { meta: SessionMeta; messages: ChatMessageData[] } => ({
  meta: { id: `s-${Date.now()}`, title: '新会话', updatedAt: Date.now() },
  messages: [],
});

export function WorkspacePage({ user, onLogout }: { user: SessionUser; onLogout: () => void }) {
  const { events, status, error, start, stop, reset } = useNdjsonStream('/api/v1/demo/stream');
  const [sessions, setSessions] = useState([newSession()]);
  const [currentId, setCurrentId] = useState(sessions[0].meta.id);
  const [input, setInput] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);
  const sealedRef = useRef(false);

  const current = sessions.find((s) => s.meta.id === currentId) ?? sessions[0];

  // 流结束 → 把当前流固化为一条 assistant 消息
  useEffect(() => {
    if (status === 'done' && events.length && !sealedRef.current) {
      sealedRef.current = true;
      setSessions((prev) =>
        prev.map((s) =>
          s.meta.id === currentId
            ? { ...s, messages: [...s.messages, { role: 'assistant', events, streaming: false }] }
            : s,
        ),
      );
      reset();
    }
  }, [status, events, currentId, reset]);

  // 自动滚底
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [current.messages.length, events.length, status]);

  const sendTask = () => {
    const text = input.trim();
    if (!text || status === 'streaming') return;
    sealedRef.current = false;
    setSessions((prev) =>
      prev.map((s) =>
        s.meta.id === currentId
          ? {
              ...s,
              meta: { ...s.meta, title: s.meta.title === '新会话' ? text.slice(0, 20) : s.meta.title, updatedAt: Date.now() },
              messages: [...s.messages, { role: 'user' as const, text }],
            }
          : s,
      ),
    );
    setInput('');
    void start({
      url: '/api/v1/tasks',
      method: 'POST',
      body: { text },
      headers: authHeaders(),
      on401: () => {
        clearToken();
        onLogout();
      },
    });
  };

  const newChat = () => {
    if (status === 'streaming') stop();
    const s = newSession();
    sealedRef.current = false;
    setSessions((prev) => [...prev, s]);
    setCurrentId(s.meta.id);
    reset();
  };

  const liveMessages = useMemo<ChatMessageData[]>(
    () => (events.length || status === 'streaming'
      ? [...current.messages, { role: 'assistant', events, streaming: status === 'streaming' }]
      : current.messages),
    [current.messages, events, status],
  );

  const currentAgent = deriveCurrentAgent(events);

  return (
    <div className="app-shell">
      <AppSidebar
        sessions={sessions.map((s) => s.meta)}
        currentId={currentId}
        onSelect={(id) => {
          if (status === 'streaming') stop();
          sealedRef.current = true; // 切走不固化当前流
          setCurrentId(id);
          reset();
        }}
        onNew={newChat}
        user={user}
        onLogout={() => {
          if (status === 'streaming') stop();
          onLogout();
        }}
      />
      <main className="chat-main">
        <header className="chat-header">
          <h2>{current.meta.title}</h2>
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
        {error && <div className="banner err">{error}</div>}
        <footer className="input-bar">
          <ModelPicker />
          <input
            className="task-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入任务，回车发送…"
            onKeyDown={(e) => e.key === 'Enter' && sendTask()}
            disabled={status === 'streaming'}
          />
          <button className="send" onClick={sendTask} disabled={status === 'streaming' || !input.trim()}>
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
