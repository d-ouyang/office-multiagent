// md.worker.ts —— markdown 解析放 Worker（大文本不卡主线程，p6.2）。
// 输入 {id, text}，输出 {id, html}（已 DOMPurify 消毒）。
import { marked } from 'marked';
import DOMPurify from 'dompurify';

self.onmessage = (e: MessageEvent<{ id: number; text: string }>) => {
  const { id, text } = e.data;
  try {
    const html = DOMPurify.sanitize(marked.parse(text, { async: false }) as string);
    (self as unknown as Worker).postMessage({ id, html });
  } catch (err) {
    (self as unknown as Worker).postMessage({ id, html: '', error: String(err) });
  }
};
