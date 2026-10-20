// 工作台（p6.1）：登录后发真实任务到 /tasks（NDJSON 流式），渲染执行过程 + Agent 徽章。
// 保留"播放演示"（canned 流）便于无 LLM key 时看 UI；"发送任务"走真链路。
import { useState } from 'react';

import EventTimeline from '../components/EventTimeline';
import { useNdjsonStream } from '../hooks/useNdjsonStream';
import { agentLabel, deriveCurrentAgent } from '../lib/derive';
import { authHeaders, clearToken } from '../lib/api';

export function WorkspacePage({ onLogout }: { onLogout: () => void }) {
  const { events, status, error, start, stop } = useNdjsonStream('/api/v1/demo/stream');
  const currentAgent = deriveCurrentAgent(events);
  const [task, setTask] = useState('');

  const sendTask = () => {
    const text = task.trim();
    if (!text || status === 'streaming') return;
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

  return (
    <div className="page">
      <header>
        <h1>office-multiagent</h1>
        <p>智能办公助手 · 真实任务工作台</p>
      </header>
      <div className="controls">
        <input
          className="task-input"
          value={task}
          onChange={(e) => setTask(e.target.value)}
          placeholder="例如：帮我查一下公司的年假制度"
          onKeyDown={(e) => e.key === 'Enter' && sendTask()}
        />
        <button onClick={sendTask} disabled={status === 'streaming' || !task.trim()}>
          发送任务
        </button>
        <button onClick={stop} disabled={status !== 'streaming'}>
          中断
        </button>
        <button onClick={() => void start()} disabled={status === 'streaming'}>
          播放演示
        </button>
        <button className="ghost" onClick={onLogout}>
          退出登录
        </button>
        <span className={`badge ${status}`}>{status}</span>
        {currentAgent && (
          <span className="agent-now">
            当前回答：<span className="badge agent">{agentLabel(currentAgent.agent)}</span>
          </span>
        )}
      </div>
      {error && <div className="banner err">{error}</div>}
      <EventTimeline events={events} isStreaming={status === 'streaming'} />
    </div>
  );
}

export default WorkspacePage;
