// 过程按事件顺序展开：思考、阶段回答、工具调用。最后一段正文由消息本体单独显示。
import { useState } from 'react';

import type { ProcessStep, ToolCall } from '../lib/derive';
import { formatDuration } from '../lib/format';
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

export function ProcessTrace({
  steps,
  durationMs,
  streaming,
}: {
  steps: ProcessStep[];
  durationMs?: number;
  streaming: boolean;
}) {
  const [open, setOpen] = useState(streaming);
  if (!steps.length) return null;
  const title = streaming ? '进行中' : durationMs != null ? `已完成 ${formatDuration(durationMs)}` : '过程';
  return (
    <div className="process">
      <button type="button" className="fold-head" onClick={() => setOpen((v) => !v)}>
        <span className={`arrow ${open ? 'open' : ''}`}>▸</span>
        {title}
        {streaming && <span className="live-dot" />}
        <span className="fold-meta">{steps.length} 步</span>
      </button>
      {open && (
        <div className="process-body">
          {steps.map((step, index) => {
            if (step.kind === 'thinking') {
              return <ThinkingBlock key={`t-${index}`} text={step.text} durationMs={step.durationMs} />;
            }
            if (step.kind === 'answer') {
              return <MarkdownView key={`a-${index}`} text={step.text} />;
            }
            return <ToolBlock key={step.call.id || `c-${index}`} call={step.call} />;
          })}
        </div>
      )}
    </div>
  );
}

function ThinkingBlock({ text, durationMs }: { text: string; durationMs?: number }) {
  const [open, setOpen] = useState(false);
  const elapsed = durationMs != null && durationMs > 0 ? formatDuration(durationMs) : '';
  return (
    <div className="process-mod">
      <button type="button" className="fold-head" onClick={() => setOpen((v) => !v)}>
        <span className={`arrow ${open ? 'open' : ''}`}>▸</span>
        <span>深度思考{elapsed ? ` ${elapsed}` : ''}</span>
        <span className="fold-meta">{text.length} 字</span>
      </button>
      {open && <pre className="think-scroll">{text}</pre>}
    </div>
  );
}

function ToolBlock({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(false);
  const mark = call.status === 'completed' ? '✓' : call.status === 'error' ? '✗' : '…';
  return (
    <div className="process-mod">
      <button type="button" className="fold-head" onClick={() => setOpen((v) => !v)}>
        <span className={`arrow ${open ? 'open' : ''}`}>▸</span>
        <span className={`step-status ${call.status}`}>{mark}</span>
        运行 {call.name || '工具'}
        {call.durationMs != null && <span className="fold-meta">{formatDuration(call.durationMs)}</span>}
      </button>
      {open && (
        <div className="tool-detail">
          <code>{JSON.stringify(call.input)}</code>
          {call.result && <pre className="think-scroll">{call.result}</pre>}
          {call.error && <p className="account-err">{call.error}</p>}
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
