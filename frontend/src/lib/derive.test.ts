import { describe, expect, it } from 'vitest';

import {
  deriveArtifacts,
  deriveContent,
  deriveSources,
  deriveThinking,
  deriveToolCalls,
} from './derive';
import type { StreamEvent } from '../types';

const ev = (type: StreamEvent['type'], data: Record<string, unknown>, seq = 0): StreamEvent => ({
  type,
  run_id: 'r',
  turn_id: 't',
  seq,
  ts: 0,
  data,
});

describe('deriveToolCalls', () => {
  it('按 tool_id 归并 start/observation/end，保持顺序', () => {
    const calls = deriveToolCalls([
      ev('tool_call_start', { tool_id: 'a', name: 'web_search', input: { q: 1 } }, 1),
      ev('tool_call_start', { tool_id: 'b', name: 'read', input: {} }, 2),
      ev('observation', { tool_id: 'a', text: '结果A' }, 3),
      ev('tool_call_end', { tool_id: 'a', name: 'web_search', success: true, duration_ms: 12 }, 4),
    ]);
    expect(calls.map((c) => c.id)).toEqual(['a', 'b']);
    expect(calls[0]).toMatchObject({ status: 'completed', result: '结果A', durationMs: 12 });
    expect(calls[1].status).toBe('running'); // b 还没 end
  });

  it('success=false → error 且带 error', () => {
    const calls = deriveToolCalls([
      ev('tool_call_start', { tool_id: 'a', name: 'bash', input: {} }, 1),
      ev('tool_call_end', { tool_id: 'a', name: 'bash', success: false, error: 'boom' }, 2),
    ]);
    expect(calls[0]).toMatchObject({ status: 'error', error: 'boom' });
  });
});

describe('derive 文本/产物/来源', () => {
  const events = [
    ev('thinking_delta', { delta: '思' }, 1),
    ev('thinking_delta', { delta: '考' }, 2),
    ev('content_delta', { delta: '答' }, 3),
    ev('content_delta', { delta: '案' }, 4),
    ev('artifact', { asset_id: 'a1', type: 'excel', name: '报表.xlsx' }, 5),
    ev('source', { source_id: 's1', type: 'web_url', title: '参考', url: 'http://x' }, 6),
  ];
  it('拼接思考/正文', () => {
    expect(deriveThinking(events)).toBe('思考');
    expect(deriveContent(events)).toBe('答案');
  });
  it('抽取产物/来源', () => {
    expect(deriveArtifacts(events)).toEqual([{ asset_id: 'a1', type: 'excel', name: '报表.xlsx', storage_url: undefined }]);
    expect(deriveSources(events)).toEqual([{ source_id: 's1', type: 'web_url', title: '参考', url: 'http://x' }]);
  });
});
