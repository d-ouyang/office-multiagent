import { describe, expect, it } from 'vitest';

import {
  agentLabel,
  deriveFailure,
  deriveArtifacts,
  deriveContent,
  deriveCurrentAgent,
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

describe('deriveCurrentAgent（p5.2 当前回答者徽章）', () => {
  it('过滤 planner/orchestrator，取最近的业务 Agent', () => {
    const events = [
      ev('status', { agent: 'planner', state: 'done' }, 1),
      ev('status', { agent: 'rag_retrieval', state: 'running' }, 2),
      ev('content_delta', { delta: '答' }, 3),
    ];
    expect(deriveCurrentAgent(events)).toEqual({ agent: 'rag_retrieval', state: 'running' });
  });

  it('done 之后仍保留本次回答者', () => {
    const events = [
      ev('status', { agent: 'planner', state: 'done' }, 1),
      ev('status', { agent: 'data_analysis', state: 'running' }, 2),
      ev('status', { agent: 'data_analysis', state: 'done' }, 3),
      ev('done', { status: 'single' }, 4),
    ];
    expect(deriveCurrentAgent(events)?.agent).toBe('data_analysis');
  });

  it('只有编排角色时返回 null', () => {
    const events = [ev('status', { agent: 'planner', state: 'done' }, 1)];
    expect(deriveCurrentAgent(events)).toBeNull();
    expect(deriveCurrentAgent([])).toBeNull();
  });

  it('agentLabel 中文映射；未知类型原样返回', () => {
    expect(agentLabel('rag_retrieval')).toBe('知识库问答 Agent');
    expect(agentLabel('no_such')).toBe('no_such');
  });
});

describe('deriveFailure（p6.12b 失败/暂停专门展示）', () => {
  const ev = (type: string, data: Record<string, unknown>) =>
    ({ type, run_id: 'r', turn_id: 't', seq: 1, ts: 0, data }) as never;

  it('quota_paused → quota 暂停（带余额/所需）', () => {
    const f = deriveFailure([
      ev('quota_paused', { reason: '余额不足，已暂停', balance: -37798, needed: 2000 }),
      ev('done', { status: 'paused_insufficient_quota' }),
    ]);
    expect(f?.kind).toBe('quota');
    expect(f?.title).toBe('余额不足，任务已暂停');
    expect(f?.balance).toBe(-37798);
    expect(f?.needed).toBe(2000);
  });

  it('error 事件 → error（带 code）', () => {
    const f = deriveFailure([ev('error', { message: '网关超时', code: 'GATEWAY_TIMEOUT' })]);
    expect(f?.kind).toBe('error');
    expect(f?.reason).toBe('网关超时');
    expect(f?.code).toBe('GATEWAY_TIMEOUT');
  });

  it('仅 done(paused_*) 兜底 → quota', () => {
    const f = deriveFailure([ev('done', { status: 'paused_insufficient_quota' })]);
    expect(f?.kind).toBe('quota');
  });

  it('正常完成无失败 → null', () => {
    expect(deriveFailure([ev('content_delta', { delta: 'hi' }), ev('done', { status: 'done' })])).toBeNull();
  });
});
