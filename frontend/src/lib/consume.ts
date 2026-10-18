// 消费 Response 的 NDJSON 流：读 ReadableStream → TextDecoder → LineBuffer → parseEvent 回调。
// §15.2 的 Worker 卸载（逐行 parse 放 Worker / MD 渲染放 Worker）留作后续优化，
// 复用同一 LineBuffer + parseEvent，避免引入未测分支。
import { LineBuffer, parseEvent } from './ndjson';
import type { StreamEvent } from '../types';

export async function consumeNdjson(
  res: Response,
  onEvent: (e: StreamEvent) => void,
): Promise<void> {
  if (!res.body) throw new Error('响应无 body（非流式响应）');
  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  const buffer = new LineBuffer();

  const emit = (line: string) => {
    const ev = parseEvent(line);
    if (ev) onEvent(ev);
  };

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    const chunk = decoder.decode(value, { stream: true });
    for (const line of buffer.push(chunk)) emit(line);
  }
  // 收尾：flush 解码器 + 行缓冲
  const tail = decoder.decode();
  if (tail) for (const line of buffer.push(tail)) emit(line);
  for (const line of buffer.flush()) emit(line);
}
