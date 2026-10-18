// 执行过程全展示（§15.1）：思考流 + 工具调用折叠条 + 正文 + 产物/来源 + 结束态。
import { useMemo } from 'react';

import ToolCallsCollapse from './ToolCallsCollapse';
import {
  deriveArtifacts,
  deriveContent,
  deriveSources,
  deriveThinking,
  deriveToolCalls,
} from '../lib/derive';
import type { StreamEvent } from '../types';

export function EventTimeline({
  events,
  isStreaming,
}: {
  events: StreamEvent[];
  isStreaming: boolean;
}) {
  const toolCalls = useMemo(() => deriveToolCalls(events), [events]);
  const content = useMemo(() => deriveContent(events), [events]);
  const thinking = useMemo(() => deriveThinking(events), [events]);
  const artifacts = useMemo(() => deriveArtifacts(events), [events]);
  const sources = useMemo(() => deriveSources(events), [events]);
  const done = events.some((e) => e.type === 'done');
  const error = events.find((e) => e.type === 'error');
  const paused = events.find((e) => e.type === 'quota_paused');

  return (
    <div className="timeline">
      {thinking && (
        <details className="thinking">
          <summary>深度思考（{thinking.length} 字）</summary>
          <pre>{thinking}</pre>
        </details>
      )}
      {toolCalls.length > 0 && (
        <ToolCallsCollapse toolCalls={toolCalls} isStreaming={isStreaming} />
      )}
      {content && <div className="content">{content}</div>}
      {paused && (
        <div className="banner warn">额度不足已暂停：{String(paused.data.reason ?? '')}</div>
      )}
      {error && <div className="banner err">错误：{String(error.data.message ?? '')}</div>}
      {artifacts.length > 0 && (
        <div className="block">
          <h4>产物 ({artifacts.length})</h4>
          <ul>
            {artifacts.map((a) => (
              <li key={a.asset_id}>
                {a.name ?? a.asset_id} <span className="muted">[{a.type}]</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {sources.length > 0 && (
        <div className="block">
          <h4>来源 ({sources.length})</h4>
          <ul>
            {sources.map((s) => (
              <li key={s.source_id}>
                {s.url ? (
                  <a href={s.url} target="_blank" rel="noreferrer">
                    {s.title ?? s.url}
                  </a>
                ) : (
                  s.title ?? s.source_id
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {done && <div className="banner ok">✓ 任务完成</div>}
    </div>
  );
}

export default EventTimeline;
