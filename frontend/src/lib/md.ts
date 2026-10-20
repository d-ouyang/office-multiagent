// markdown → HTML（p6.2）。
// 判断纪律（用户要求）：文本量大才开 Worker，少量直接主线程同步解析——
// 阈值 20_000 字符：主线程解析几百微秒的事不值得 postMessage 往返。
// 全部输出过 DOMPurify（流式渲染的是 LLM 输出，必须防注入）。
import { marked } from 'marked';
import DOMPurify from 'dompurify';

const WORKER_THRESHOLD = 20_000;

let worker: Worker | null = null;
let seq = 0;
const pending = new Map<number, (html: string) => void>();

function getWorker(): Worker {
  if (!worker) {
    worker = new Worker(new URL('./md.worker.ts', import.meta.url), { type: 'module' });
    worker.onmessage = (e: MessageEvent<{ id: number; html: string }>) => {
      pending.get(e.data.id)?.(e.data.html);
      pending.delete(e.data.id);
    };
  }
  return worker;
}

/** 同步解析（小文本直接用）。 */
export function renderMarkdown(text: string): string {
  return DOMPurify.sanitize(marked.parse(text ?? '', { async: false }) as string);
}

/** 带判断的解析：大文本走 Worker（异步），小文本主线程同步。 */
export function renderMarkdownSmart(text: string): Promise<string> {
  if (!text) return Promise.resolve('');
  if (text.length < WORKER_THRESHOLD) return Promise.resolve(renderMarkdown(text));
  const id = ++seq;
  return new Promise((resolve) => {
    pending.set(id, resolve);
    getWorker().postMessage({ id, text });
  });
}
