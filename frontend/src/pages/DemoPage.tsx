// 演示页：拉 /api/v1/demo/stream（经网关白名单透传）渲染执行过程。
import EventTimeline from '../components/EventTimeline';
import { useNdjsonStream } from '../hooks/useNdjsonStream';

export function DemoPage() {
  const { events, status, error, start, stop } = useNdjsonStream('/api/v1/demo/stream');
  return (
    <div className="page">
      <header>
        <h1>office-multiagent</h1>
        <p>多 Agent 执行过程可视化（NDJSON 流式，经网关透传）</p>
      </header>
      <div className="controls">
        <button onClick={start} disabled={status === 'streaming'}>
          开始演示
        </button>
        <button onClick={stop} disabled={status !== 'streaming'}>
          中断
        </button>
        <span className={`badge ${status}`}>{status}</span>
      </div>
      {error && <div className="banner err">{error}</div>}
      <EventTimeline events={events} isStreaming={status === 'streaming'} />
    </div>
  );
}

export default DemoPage;
