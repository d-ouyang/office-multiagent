// 把事件流折叠成视图需要的数据（ToolCallsCollapse 的 toolCalls / 正文 / 思考流）。
import type { StreamEvent } from '../types';

export interface ToolCall {
  id: string;
  name: string;
  status: 'running' | 'completed' | 'error';
  input: Record<string, unknown>;
  result?: string;
  error?: string;
  durationMs?: number;
}

/** 按 tool_id 归并 tool_call_start / observation / tool_call_end，保持出现顺序。 */
export function deriveToolCalls(events: StreamEvent[]): ToolCall[] {
  const map = new Map<string, ToolCall>();
  const order: string[] = [];
  for (const ev of events) {
    if (ev.type === 'tool_call_start') {
      const id = String(ev.data.tool_id ?? '');
      if (!map.has(id)) order.push(id);
      map.set(id, {
        id,
        name: String(ev.data.name ?? ''),
        status: 'running',
        input: (ev.data.input ?? {}) as Record<string, unknown>,
      });
    } else if (ev.type === 'observation') {
      const tc = map.get(String(ev.data.tool_id ?? ''));
      if (tc) tc.result = String(ev.data.text ?? '');
    } else if (ev.type === 'tool_call_end') {
      const tc = map.get(String(ev.data.tool_id ?? ''));
      if (tc) {
        tc.status = ev.data.success === false ? 'error' : 'completed';
        if (typeof ev.data.duration_ms === 'number') tc.durationMs = ev.data.duration_ms;
        if (ev.data.error) tc.error = String(ev.data.error);
      }
    }
  }
  return order.map((id) => map.get(id)!).filter(Boolean);
}

export function deriveContent(events: StreamEvent[]): string {
  return events
    .filter((e) => e.type === 'content_delta')
    .map((e) => String(e.data.delta ?? ''))
    .join('');
}

export function deriveThinking(events: StreamEvent[]): string {
  return events
    .filter((e) => e.type === 'thinking_delta')
    .map((e) => String(e.data.delta ?? ''))
    .join('');
}

export function deriveArtifacts(events: StreamEvent[]): Array<{ asset_id: string; type: string; name?: string; storage_url?: string }> {
  return events
    .filter((e) => e.type === 'artifact')
    .map((e) => ({
      asset_id: String(e.data.asset_id ?? ''),
      type: String(e.data.type ?? ''),
      name: e.data.name ? String(e.data.name) : undefined,
      storage_url: e.data.storage_url ? String(e.data.storage_url) : undefined,
    }));
}

export function deriveSources(events: StreamEvent[]): Array<{ source_id: string; type: string; title?: string; url?: string }> {
  return events
    .filter((e) => e.type === 'source')
    .map((e) => ({
      source_id: String(e.data.source_id ?? ''),
      type: String(e.data.type ?? ''),
      title: e.data.title ? String(e.data.title) : undefined,
      url: e.data.url ? String(e.data.url) : undefined,
    }));
}
