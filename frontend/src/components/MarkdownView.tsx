// Markdown 正文渲染（p6.2→p6.10 打字机队列）：
// - **缓冲队列 + rAF 匀速播放**：delta 到达只更新目标文本（textRef），渲染循环每帧从
//   "已显示位置"向目标推进 step = ceil(剩余/8)——LLM 出字再快也匀速逐字滚动（对齐 RAG
//   的逐字感），LLM 停止后剩余内容快速追完；渲染频率恒定 60fps，与 delta 到达率解耦
//   （大文件频繁 delta 不会引发高频 DOM 重渲）。
// - markdown 每帧解析一次"已显示前缀"（截断语法由 marked 容错）；≥20k 字解析走 Worker（lib/md）。
import { useEffect, useRef, useState } from 'react';

import { renderMarkdownSmart } from '../lib/md';

const STEP_DIVISOR = 8; // 追帧除数：剩余越长每帧推进越多（8 帧≈130ms 内追平最新）

export function MarkdownView({ text, streaming }: { text: string; streaming?: boolean }) {
  const [shown, setShown] = useState(streaming ? 0 : text.length);
  const [html, setHtml] = useState('');
  const textRef = useRef(text);
  textRef.current = text;

  // 流式：rAF 匀速推进 shown（队列消费）；结束/历史：立即显示全文
  useEffect(() => {
    if (!streaming) {
      setShown(textRef.current.length);
      return;
    }
    let raf = 0;
    const tick = () => {
      setShown((prev) => {
        const target = textRef.current.length;
        if (prev >= target) return prev;
        const step = Math.max(1, Math.ceil((target - prev) / STEP_DIVISOR));
        return Math.min(prev + step, target);
      });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [streaming]);

  // shown 每帧变化 → 解析渲染一次"已显示前缀"
  useEffect(() => {
    let alive = true;
    renderMarkdownSmart(text.slice(0, shown)).then((h) => alive && setHtml(h));
    return () => {
      alive = false;
    };
  }, [shown, text, streaming]);

  return (
    <div
      className={`md-body${streaming ? ' streaming' : ''}`}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

export default MarkdownView;
