import { useState } from 'react';

import type { ContextUsage } from '../lib/derive';
import { fmtWindow } from './ModelPicker';

function fmt(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}K`;
  return String(n);
}

export default function ContextRing({
  usage,
  windowSize: windowOverride = 0,
}: {
  usage: ContextUsage | null;
  /** 当前选中模型的上下文上限。切换模型后马上换分母，不必等下一轮任务。 */
  windowSize?: number;
}) {
  const [open, setOpen] = useState(false);
  const windowSize = windowOverride > 0 ? windowOverride : usage?.window || 0;
  const used = usage?.used || 0;
  const ratio = windowSize > 0 ? Math.min(1, used / windowSize) : 0;
  const percent = Math.round(ratio * 100);
  const radius = 8;
  const circ = 2 * Math.PI * radius;
  return (
    <div className="context-ring">
      <button
        type="button"
        className="context-ring-btn"
        aria-label="上下文用量"
        title="上下文用量"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
          <circle cx="12" cy="12" r={radius} fill="none" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2.5" />
          <circle
            cx="12"
            cy="12"
            r={radius}
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeDasharray={`${circ * ratio} ${circ}`}
            strokeLinecap="round"
            transform="rotate(-90 12 12)"
          />
        </svg>
      </button>
      {open && (
        <div className="context-panel" role="dialog" aria-label="上下文用量">
          <div className="context-panel-head">
            <strong>上下文用量</strong>
            <button type="button" onClick={() => setOpen(false)} aria-label="关闭">×</button>
          </div>
          <div className="context-panel-summary">
            <span>{percent}% 已用</span>
            <span>{fmt(used)} / {fmtWindow(windowSize)} tokens</span>
          </div>
          <div className="context-bar">
            {(usage?.items ?? []).map((item) => (
              <i
                key={item.key}
                style={{ width: `${windowSize ? (item.tokens / windowSize) * 100 : 0}%`, background: item.color }}
              />
            ))}
          </div>
          <ul>
            {(usage?.items ?? []).map((item) => (
              <li key={item.key}>
                <span><i style={{ background: item.color }} />{item.label}</span>
                <span>{fmt(item.tokens)}</span>
              </li>
            ))}
            {!usage && <li>这个会话还没有上下文记录。</li>}
          </ul>
        </div>
      )}
    </div>
  );
}