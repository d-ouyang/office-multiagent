// 深度思考 / 步骤折叠面板（p6.2）：默认折叠；折叠中照常累积，展开即见实时流式内容。
import { useState } from 'react';

import type { ToolCall } from '../lib/derive';
import MarkdownView from './MarkdownView';

export function ThinkingPanel({ text, streaming }: { text: string; streaming: boolean }) {
  const [open, setOpen] = useState(false);
  if (!text) return null;
  return (
    <div className="fold-panel thinking">
      <button className="fold-head" onClick={() => setOpen(!open)}>
        <span className={`arrow ${open ? 'open' : ''}`}>▸</span>
        深度思考
        {streaming && <span className="live-dot" />}
        <span className="fold-meta">{text.length} 字</span>
      </button>
      {open && (
        <div className="fold-body">
          <MarkdownView text={text} streaming={streaming} />
        </div>
      )}
    </div>
  );
}

export function StepsPanel({ toolCalls, streaming }: { toolCalls: ToolCall[]; streaming: boolean }) {
  const [open, setOpen] = useState(false);
  if (!toolCalls.length) return null;
  return (
    <div className="fold-panel steps">
      <button className="fold-head" onClick={() => setOpen(!open)}>
        <span className={`arrow ${open ? 'open' : ''}`}>▸</span>
        查看步骤
        {streaming && <span className="live-dot" />}
        <span className="fold-meta">{toolCalls.length} 次调用</span>
      </button>
      {open && (
        <div className="fold-body steps-body">
          {toolCalls.map((tc) => (
            <div key={tc.id} className={`step-row ${tc.status}`}>
              <span className="step-status">
                {tc.status === 'completed' ? '✓' : tc.status === 'error' ? '✗' : '…'}
              </span>
              <span className="step-name">{tc.name}</span>
              <code className="step-input">{JSON.stringify(tc.input)}</code>
              {tc.durationMs != null && <span className="step-dur">{tc.durationMs}ms</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
