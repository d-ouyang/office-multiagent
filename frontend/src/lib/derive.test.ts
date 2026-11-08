import { describe, expect, it } from 'vitest';
import { deriveAskUser } from './derive';

import {
  agentLabel,
  deriveFailure,
  deriveArtifacts,
  deriveContent,
  deriveProcess,
  deriveCurrentAgent,
  deriveReplyMeta,
  pauseText,
  quotaPauseText,
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

describe('deriveProcess', () => {
  it('按顺序切开，最后一段正文才是结果', () => {
    const view = deriveProcess([
      ev('thinking_delta', { delta: '先想' }, 1),
      ev('content_delta', { delta: '阶段结论' }, 2),
      ev('tool_call_start', { tool_id: 'q', name: 'db_query', input: { sql: 'SELECT 1' } }, 3),
      ev('tool_call_end', { tool_id: 'q', success: true }, 4),
      ev('thinking_delta', { delta: '再想' }, 5),
      ev('content_delta', { delta: '最终回答' }, 6),
    ]);
    expect(view.result).toBe('最终回答');
    expect(view.steps.map((step) => step.kind)).toEqual(['thinking', 'answer', 'tool', 'thinking']);
    expect(view.steps[0]).toMatchObject({ text: '先想' });
    expect(view.steps[1]).toMatchObject({ text: '阶段结论' });
    expect(view.steps[2].kind === 'tool' && view.steps[2].call.name).toBe('db_query');
  });

  it('同一段思考用首尾时间算耗时', () => {
    const think = (delta: string, seq: number, ts: number) =>
      ({ type: 'thinking_delta', run_id: 'r', turn_id: 't', seq, ts, data: { delta } }) as StreamEvent;
    const view = deriveProcess([
      think('先', 1, 1_000),
      think('想', 2, 2_500),
      { type: 'content_delta', run_id: 'r', turn_id: 't', seq: 3, ts: 3_000, data: { delta: '答' } },
    ]);
    expect(view.steps[0]).toMatchObject({ kind: 'thinking', text: '先想', durationMs: 1_500 });
  });
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

describe('deriveReplyMeta', () => {
  it('从 done 取用量和模型，耗时为首尾事件差', () => {
    const meta = deriveReplyMeta([
      { ...ev('content_delta', { delta: '答' }, 1), ts: 1000 },
      { ...ev('done', { status: 'single', tokens_used: 3011, model: 'deepseek-chat' }, 2), ts: 4200 },
    ]);
    expect(meta).toEqual({ tokens: 3011, model: 'deepseek-chat', durationMs: 3200, endedAt: 4200 });
  });

  it('没有用量字段时不把 0 当成真实消耗', () => {
    const meta = deriveReplyMeta([ev('done', { status: 'done' })]);
    expect(meta.tokens).toBeUndefined();
    expect(meta.model).toBeUndefined();
  });
});

describe('pauseText（p7.1 暂停原因）', () => {
  it('quota 只保留预扣额，不把暂停当时的余额写进文案', () => {
    const t = pauseText('paused_insufficient_quota', { balance: 0, needed: 2000 });
    expect(t).toContain('余额不足');
    expect(t).toContain('2000');
    expect(t).not.toContain('继续');
  });
  it('user / error 各自文案', () => {
    expect(pauseText('paused_user')).toContain('暂停');
    expect(pauseText('paused_error')).toContain('出错');
    expect(pauseText('failed')).toContain('重试');
  });
  it('未知状态兜底', () => {
    expect(pauseText('weird')).toBe('任务已暂停');
  });
  it('当前余额够付预扣时不提示，不够时用实时余额', () => {
    expect(quotaPauseText(2000, 1_000_000)).toBeNull();
    expect(quotaPauseText(2000, null)).toBeNull();
    const low = quotaPauseText(2000, 0);
    expect(low).toContain('当前余额 0');
    expect(low).toContain('2,000');
    expect(low).not.toContain('继续');
  });
});

describe('deriveAskUser（2.1.0 P1-1 HITL）', () => {
  it('取最后一个 ask_user 载荷', () => {
    const events = [
      { type: 'status', run_id: 'r', turn_id: 't', seq: 1, ts: 1, data: { agent: 'planner' } },
      {
        type: 'ask_user',
        run_id: 'r',
        turn_id: 't',
        seq: 2,
        ts: 2,
        data: { question: '要哪个文件？', options: ['a.csv'], need_file: true, file_hint: 'csv' },
      },
    ];
    const ask = deriveAskUser(events as never[]);
    expect(ask?.questions).toHaveLength(1);
    expect(ask?.questions[0].question).toBe('要哪个文件？');
    expect(ask?.questions[0].need_file).toBe(true);
    expect(deriveAskUser([])).toBeNull();
  });
});
