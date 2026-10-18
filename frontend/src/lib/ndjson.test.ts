import { describe, expect, it } from 'vitest';

import { LineBuffer, parseEvent } from './ndjson';

describe('LineBuffer', () => {
  it('按 \n 切行，残行留到下次', () => {
    const b = new LineBuffer();
    expect(b.push('{"a":1}\n{"b"')).toEqual(['{"a":1}']);
    expect(b.push(':2}\n{"c":3}\n')).toEqual(['{"b":2}', '{"c":3}']);
    expect(b.flush()).toEqual([]);
  });

  it('一行被拆成多个分片也能正确拼回', () => {
    const b = new LineBuffer();
    expect(b.push('{"he')).toEqual([]);
    expect(b.push('llo":1}')).toEqual([]);
    expect(b.push('\n')).toEqual(['{"hello":1}']);
  });

  it('过滤空行；flush 吐出不带换行的末行', () => {
    const b = new LineBuffer();
    expect(b.push('\n\n{"x":1}\n\n')).toEqual(['{"x":1}']);
    b.push('{"y":2}');
    expect(b.flush()).toEqual(['{"y":2}']);
    expect(b.flush()).toEqual([]);
  });
});

describe('parseEvent', () => {
  it('解析合法事件', () => {
    const ev = parseEvent('{"type":"done","run_id":"r","turn_id":"t","seq":1,"ts":1,"data":{}}');
    expect(ev?.type).toBe('done');
    expect(ev?.seq).toBe(1);
  });

  it('坏 JSON 返回 null（不抛）', () => {
    expect(parseEvent('{not json')).toBeNull();
  });

  it('缺 type/seq 返回 null', () => {
    expect(parseEvent('{"foo":1}')).toBeNull();
    expect(parseEvent('{"type":"done"}')).toBeNull();
  });
});
