// 演示页：拉 /api/v1/demo/stream（经网关白名单透传）渲染执行过程。
import EventTimeline from '../components/EventTimeline';
import Notice from '../components/Notice';
import { useNdjsonStream } from '../hooks/useNdjsonStream';
import { describeError } from '../lib/apiError';
import { agentLabel, deriveCurrentAgent } from '../lib/derive';

export function DemoPage() {
  const { events, status, error, start, stop, clearError } = useNdjsonStream('/api/v1/demo/stream');
  const currentAgent = deriveCurrentAgent(events);
  return (
    <div className="page">
      <header>
        <h1>office-multiagent</h1>
        <p>多 Agent 执行过程可视化（NDJSON 流式，经网关透传）</p>
      </header>
      <div className="controls">
        <button onClick={() => void start()} disabled={status === 'streaming'}>
          开始演示
        </button>
        <button onClick={stop} disabled={status !== 'streaming'}>
          中断
        </button>
        <span className={`badge ${status}`}>{status}</span>
        {currentAgent && (
          <span className="agent-now">
            当前回答：<span className="badge agent">{agentLabel(currentAgent.agent)}</span>
          </span>
        )}
      </div>
      {error && <Notice notice={describeError(error)} onClose={clearError} />}
      <EventTimeline events={events} isStreaming={status === 'streaming'} />
    </div>
  );
}

export default DemoPage;
