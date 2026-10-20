// Markdown 正文渲染（p6.2）：smart 解析（大文本走 Worker）+ 流式期间实时更新。
import { useEffect, useState } from 'react';

import { renderMarkdownSmart } from '../lib/md';

export function MarkdownView({ text, streaming }: { text: string; streaming?: boolean }) {
  const [html, setHtml] = useState('');

  useEffect(() => {
    let alive = true;
    renderMarkdownSmart(text).then((h) => alive && setHtml(h));
    return () => {
      alive = false;
    };
  }, [text]);

  return (
    <div
      className={`md-body${streaming ? ' streaming' : ''}`}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

export default MarkdownView;
