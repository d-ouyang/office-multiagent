import { describe, expect, it, vi } from 'vitest';

import { consumeNdjson } from './consume';
import type { StreamEvent } from '../types';

/** 造一个假 Response：body 是按 chunks 逐段吐字节的 ReadableStream。 */
function fakeRes(chunks: string[]): Response {
  const enc = new TextEncoder();
  let i = 0;
  const body = new ReadableStream<Uint8Array>({
    pull(c) {
      if (i < chunks.length) c.enqueue(enc.encode(chunks[i++]));
      else c.close();
    },
  });
  return { body } as unknown as Response;
}

describe('consumeNdjson', () => {
  it('跨分片逐行解析，按序回调', async () => {
    const chunks = [
      '{"type":"thinking_delta","run_id":"r","turn_id":"t","seq":1,"ts":1,"data":{"delta":"a"}}\n{"type":"cont',
      'ent_delta","run_id":"r","turn_id":"t","seq":2,"ts":2,"data":{"delta":"b"}}\n',
      '{"type":"done","run_id":"r","turn_id":"t","seq":3,"ts":3,"data":{}}\n',
    ];
    const got: StreamEvent[] = [];
    await consumeNdjson(fakeRes(chunks), (e) => got.push(e));
    expect(got.map((e) => e.type)).toEqual(['thinking_delta', 'content_delta', 'done']);
    expect(got.map((e) => e.seq)).toEqual([1, 2, 3]);
  });

  it('坏行被跳过，不影响其余事件', async () => {
    const chunks = [
      'not-json-line\n{"type":"done","run_id":"r","turn_id":"t","seq":9,"ts":1,"data":{}}\n',
    ];
    const got: StreamEvent[] = [];
    await consumeNdjson(fakeRes(chunks), (e) => got.push(e));
    expect(got).toHaveLength(1);
    expect(got[0].type).toBe('done');
  });

  it('无 body 抛错', async () => {
    await expect(consumeNdjson({} as Response, vi.fn())).rejects.toThrow(/body/);
  });
});
