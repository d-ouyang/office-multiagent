// NDJSON 行解析（§15.2）：按 \n 切行 + JSON.parse，残行留缓冲区。
import type { StreamEvent } from '../types';

/**
 * 行缓冲：把任意分片拼成完整行，最后一段可能是残行、留到下次。
 * 单测覆盖：分片跨行/一行被拆多次/空行过滤。
 */
export class LineBuffer {
  private residual = '';

  /** 喂入一个文本分片，返回其中已完整的行（不含残行）。 */
  push(chunk: string): string[] {
    this.residual += chunk;
    const parts = this.residual.split('\n');
    this.residual = parts.pop() ?? ''; // 末尾可能是残行
    return parts.filter((l) => l.trim().length > 0);
  }

  /** 流结束时把残留的最后一行吐出（若完整）。 */
  flush(): string[] {
    const rest = this.residual.trim();
    this.residual = '';
    return rest ? [rest] : [];
  }
}

/**
 * 解析单行成事件；坏行 / 非事件行返回 null（流式不因单行坏数据中断）。
 * 校验最小必要字段：type 为字符串、seq 为数字。
 */
export function parseEvent(line: string): StreamEvent | null {
  try {
    const obj = JSON.parse(line) as Partial<StreamEvent>;
    if (obj && typeof obj.type === 'string' && typeof obj.seq === 'number') {
      return obj as StreamEvent;
    }
    return null;
  } catch {
    return null;
  }
}
