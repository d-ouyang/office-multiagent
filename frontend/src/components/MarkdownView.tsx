// Markdown 正文渲染（p6.2/p6.3）：smart 解析（大文本走 Worker）+ 流式期间节流防抖。
import { useEffect, useState } from 'react';

import { renderMarkdownSmart } from '../lib/md';

export function MarkdownView({ text, streaming }: { text: string; streaming?: boolean }) {
  const [html, setHtml] = useState('');

  useEffect(() => {
    let alive = true;
    if (streaming) {
      // 流式中每 chunk 重解析太频——80ms 节流（视觉仍是打字机，CPU 不炸）
      const timer = setTimeout(() => {
        renderMarkdownSmart(text).then((h) => alive && setHtml(h));
      }, 80);
      return () => {
        alive = false;
        clearTimeout(timer);
      };
    }
    renderMarkdownSmart(text).then((h) => alive && setHtml(h));
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
