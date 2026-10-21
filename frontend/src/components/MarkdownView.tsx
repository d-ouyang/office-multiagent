// Markdown 正文渲染（p6.2/p6.7/p6.9）：
// - 流式期间自适应节流：短文本（<2000 字）每 delta 直接重渲染（真逐字感，对齐 RAG）；
//   长文本 50ms 节流（全量 marked 解析 + innerHTML 替换的成本保护）。
// - 大文本（≥20k 字）解析走 Worker（lib/md）。
import { useEffect, useRef, useState } from 'react';

import { renderMarkdownSmart } from '../lib/md';

const LIVE_THRESHOLD = 2_000; // 短文本逐 delta 渲染
const THROTTLE_MS = 50;

export function MarkdownView({ text, streaming }: { text: string; streaming?: boolean }) {
  const [html, setHtml] = useState('');
  const timerRef = useRef<number | null>(null);
  const textRef = useRef(text);
  textRef.current = text; // timer 触发时渲染最新文本（不是设置时的旧快照）

  useEffect(() => {
    let alive = true;
    const render = () => renderMarkdownSmart(textRef.current).then((h) => alive && setHtml(h));

    if (streaming && text.length >= LIVE_THRESHOLD) {
      // 长文本：50ms 节流（尾帧必渲染最新文本）
      if (timerRef.current !== null) return () => { alive = false; };
      timerRef.current = window.setTimeout(() => {
        timerRef.current = null;
        render();
      }, THROTTLE_MS);
      return () => {
        alive = false;
        if (timerRef.current !== null) {
          clearTimeout(timerRef.current);
          timerRef.current = null;
        }
      };
    }
    // 短文本/已结束：直接渲染（每 delta 一次，打字机感）
    render();
    return () => {
      alive = false;
    };
  }, [text, streaming]);

  return (
    <div
      className={`md-body${streaming ? ' streaming' : ''}`}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

export default MarkdownView;
