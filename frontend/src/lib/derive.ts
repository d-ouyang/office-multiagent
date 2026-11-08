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

export type ProcessStep =
  | { kind: 'thinking'; text: string; durationMs?: number }
  | { kind: 'answer'; text: string }
  | { kind: 'tool'; call: ToolCall };

type OpenStep =
  | { kind: 'thinking'; text: string; startTs: number; endTs: number }
  | { kind: 'answer'; text: string }
  | { kind: 'tool'; call: ToolCall };

export interface ProcessView {
  steps: ProcessStep[];
  result: string;
  durationMs?: number;
}

/** 按事件顺序切段。最后一段正文是结果，它前面的思考、阶段回答和工具都是过程。 */
export function deriveProcess(events: StreamEvent[]): ProcessView {
  const ordered = events
    .map((ev, index) => ({ ev, index }))
    .sort((a, b) => a.ev.seq - b.ev.seq || a.index - b.index)
    .map((item) => item.ev);
  const steps: ProcessStep[] = [];
  const tools = new Map<string, ToolCall>();
  let open: OpenStep | null = null;

  const flush = () => {
    if (!open) return;
    if (open.kind === 'thinking') {
      if (open.text.trim()) {
        const durationMs = open.endTs > open.startTs && open.startTs > 0 ? open.endTs - open.startTs : undefined;
        steps.push({ kind: 'thinking', text: open.text, durationMs });
      }
    } else if (open.kind === 'tool' || open.text.trim()) {
      steps.push(open);
    }
    open = null;
  };

  for (const ev of ordered) {
    if (ev.type === 'thinking_delta') {
      if (!open || open.kind !== 'thinking') {
        flush();
        open = { kind: 'thinking', text: '', startTs: ev.ts, endTs: ev.ts };
      }
      open.text += String(ev.data.delta ?? '');
      if (ev.ts > 0) {
        if (open.startTs <= 0) open.startTs = ev.ts;
        open.endTs = ev.ts;
      }
    } else if (ev.type === 'content_delta') {
      if (!open || open.kind !== 'answer') {
        flush();
        open = { kind: 'answer', text: '' };
      }
      open.text += String(ev.data.delta ?? '');
    } else if (ev.type === 'tool_call_start') {
      flush();
      const id = String(ev.data.tool_id ?? '');
      const call: ToolCall = {
        id,
        name: String(ev.data.name ?? ''),
        status: 'running',
        input: (ev.data.input ?? {}) as Record<string, unknown>,
      };
      tools.set(id, call);
      steps.push({ kind: 'tool', call });
    } else if (ev.type === 'observation' || ev.type === 'tool_call_end') {
      const call = tools.get(String(ev.data.tool_id ?? ''));
      if (!call) continue;
      if (ev.type === 'observation') call.result = String(ev.data.text ?? '');
      else {
        call.status = ev.data.success === false ? 'error' : 'completed';
        if (typeof ev.data.duration_ms === 'number') call.durationMs = ev.data.duration_ms;
        if (ev.data.error) call.error = String(ev.data.error);
      }
    }
  }
  flush();

  let result = '';
  const last = steps[steps.length - 1];
  if (last?.kind === 'answer') {
    result = last.text;
    steps.pop();
  }
  const times = ordered.map((item) => item.ts).filter((n) => typeof n === 'number' && n > 0);
  const durationMs = times.length >= 2 ? times[times.length - 1] - times[0] : undefined;
  return { steps, result, durationMs };
}

export interface ContextItem {
  key: string;
  label: string;
  tokens: number;
  color: string;
}

export interface ContextUsage {
  window: number;
  used: number;
  items: ContextItem[];
}

/** 取最后一次上下文分栏。没有事件时返回空。 */
export function deriveContextUsage(events: StreamEvent[]): ContextUsage | null {
  let found: ContextUsage | null = null;
  for (const ev of events) {
    if (ev.type !== 'context_usage') continue;
    const items = Array.isArray(ev.data.items) ? ev.data.items : [];
    found = {
      window: Number(ev.data.window) || 0,
      used: Number(ev.data.used) || 0,
      items: items.map((item) => {
        const row = item as Record<string, unknown>;
        return {
          key: String(row.key ?? ''),
          label: String(row.label ?? ''),
          tokens: Number(row.tokens) || 0,
          color: String(row.color ?? '#8b949e'),
        };
      }),
    };
  }
  return found;
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

/** 流程图和图表的结构。界面按 kind 绘制，不解析 observation 文本。 */
export function deriveVisuals(events: StreamEvent[]): Array<Record<string, unknown>> {
  const visuals: Array<Record<string, unknown>> = [];
  for (const ev of events) {
    if (ev.type !== 'visual') continue;
    const payload = ev.data.payload;
    if (payload && typeof payload === 'object') visuals.push(payload as Record<string, unknown>);
  }
  return visuals;
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

/** planner / orchestrator 是编排角色，不是"回答者"——徽章只认业务 Agent。 */
const META_AGENTS = new Set(['planner', 'orchestrator']);

/** agent_type → 中文展示名（与 config/agents.yaml 的 name 对应，前端静态映射）。 */
const AGENT_LABELS: Record<string, string> = {
  general: '通用办公 Agent',
  rag_retrieval: '知识库问答 Agent',
  data_analysis: '数据分析 Agent',
  data_cleaning: '数据清洗 Agent',
  report_generation: '报表生成 Agent',
  visualization: '图表可视化 Agent',
  image_restore: '图像修复 Agent',
};

export function agentLabel(agent: string): string {
  return AGENT_LABELS[agent] ?? agent;
}

/** 最近一次出现过的业务 Agent（status 事件；running/done 都算"本次回答者"）。 */
export function deriveCurrentAgent(events: StreamEvent[]): { agent: string; state: string } | null {
  let current: { agent: string; state: string } | null = null;
  for (const ev of events) {
    if (ev.type !== 'status') continue;
    const agent = String(ev.data.agent ?? '');
    if (!agent || META_AGENTS.has(agent)) continue;
    current = { agent, state: String(ev.data.state ?? '') };
  }
  return current;
}

export interface FailureInfo {
  kind: 'quota' | 'error';
  title: string;
  reason: string;
  balance?: number;
  needed?: number;
  code?: string;
}

/** p6.12b：失败/暂停专门展示——quota_paused / error / done(paused_*|error) 归一为一个可渲染对象。
 *  之前 quota_paused 只在流式期间有临时 banner，done 后 reset() 事件被清、界面无任何痕迹（病根同 p6.7b）。 */
export function deriveFailure(events: StreamEvent[]): FailureInfo | null {
  for (const ev of events) {
    if (ev.type === 'quota_paused') {
      return {
        kind: 'quota',
        title: '余额不足，任务已暂停',
        reason: String(ev.data.reason ?? '余额不足'),
        balance: typeof ev.data.balance === 'number' ? ev.data.balance : undefined,
        needed: typeof ev.data.needed === 'number' ? ev.data.needed : undefined,
      };
    }
    if (ev.type === 'error') {
      return {
        kind: 'error',
        title: '任务失败',
        reason: String(ev.data.message ?? '未知错误'),
        code: ev.data.code ? String(ev.data.code) : undefined,
      };
    }
  }
  // 兜底：quota_paused/error 事件缺失时看 done 状态。
  // paused_input 是 HITL 等待补充输入（不是余额问题）——返回 null 交由 ask 卡片接管，
  // 否则会渲染出误导性的"余额不足"横幅（实测踩过）。
  const done = events.find((e) => e.type === 'done');
  const st = done ? String(done.data.status ?? 'done') : 'done';
  if (st === 'paused_input' || st === 'paused_budget') {
    return null; // HITL 卡片 / 预算暂停横幅接管，不走"余额不足"误导横幅
  }
  if (st.startsWith('paused')) {
    return { kind: 'quota', title: '余额不足，任务已暂停', reason: st };
  }
  if (st === 'error' || st === 'failed') {
    return { kind: 'error', title: '任务失败', reason: st };
  }
  return null;
}

export interface ReplyMeta {
  tokens?: number;
  model?: string;
  durationMs?: number;
  endedAt?: number;
  steps?: Array<{ label: string; tokens: number }>;  // p6.45：逐步用量明细（悬浮浮窗）
}

/** 回复行：done 事件上的用量/模型，以及首尾事件时间差。 */
export function deriveReplyMeta(events: StreamEvent[]): ReplyMeta {
  let tokens: number | undefined;
  let model: string | undefined;
  let steps: ReplyMeta['steps'];
  let first = 0;
  let last = 0;
  for (const ev of events) {
    if (typeof ev.ts === 'number' && ev.ts > 0) {
      if (!first) first = ev.ts;
      last = ev.ts;
    }
    if (ev.type !== 'done') continue;
    if (typeof ev.data.tokens_used === 'number') tokens = ev.data.tokens_used;
    if (ev.data.model) model = String(ev.data.model);
    if (Array.isArray(ev.data.steps) && ev.data.steps.length > 0) {
      steps = ev.data.steps
        .filter((s: { label?: unknown; tokens?: unknown }) => typeof s?.label === 'string' && typeof s?.tokens === 'number')
        .map((s: { label: string; tokens: number }) => ({ label: s.label, tokens: s.tokens }));
    }
  }
  return {
    tokens,
    model,
    steps,
    durationMs: first > 0 && last >= first ? last - first : undefined,
    endedAt: last || undefined,
  };
}

/** 余额不足横幅。数字用当前钱包，不用暂停当时记下的余额。余额已经够付这次预扣时不提示。 */
export function quotaPauseText(needed: number, balance: number | null): string | null {
  if (balance == null) return null;
  const need = Number.isFinite(needed) ? needed : 0;
  if (need > 0 && balance >= need) return null;
  if (balance > 0 && need <= 0) return null;
  const bal = balance.toLocaleString('zh-CN');
  if (need > 0) {
    return `余额不足，这次提问大约需要 ${need.toLocaleString('zh-CN')}，当前余额 ${bal}。充值后重新发送即可。`;
  }
  return `余额不足，当前余额 ${bal}。充值后重新发送即可。`;
}

export interface AskQuestion {
  question: string;
  options: string[];
  need_file: boolean;
  file_hint: string;
}

export interface AskUserPayload {
  questions: AskQuestion[];
}

/** 把任意形状（新 questions 数组 / 旧单 question / JSON 字符串）归一成
 *  AskUserPayload；无有效问题返回 null。防旧格式 paused_input 崩渲染（实测踩过）。 */
export function normalizeAsk(raw: unknown): AskUserPayload | null {
  if (raw == null) return null;
  let obj: Record<string, unknown> | null = null;
  if (typeof raw === 'string') {
    try {
      obj = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return null;
    }
  } else if (typeof raw === 'object') {
    obj = raw as Record<string, unknown>;
  }
  if (!obj) return null;
  // 兼容两种包裹：{questions:[...]} 或旧版 {question,options,...} 直接展开
  const listRaw = Array.isArray(obj.questions)
    ? obj.questions
    : [obj.question != null ? obj : null].filter(Boolean);
  const questions = (listRaw as Record<string, unknown>[])
    .map((q) => ({
      question: String(q.question ?? ''),
      options: Array.isArray(q.options) ? q.options.map(String) : [],
      need_file: !!q.need_file,
      file_hint: String(q.file_hint ?? ''),
    }))
    .filter((q) => q.question);
  return questions.length ? { questions } : null;
}

/** 2.1.0 P1-1 HITL：取流里最后一个 ask_user 载荷（模型请求补充输入，可能一次多个问题）。 */
export function deriveAskUser(events: StreamEvent[]): AskUserPayload | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const ev = events[i];
    if (ev.type === 'ask_user') {
      return normalizeAsk(ev.data);
    }
  }
  return null;
}

/** p7.1：任务暂停原因 → 横幅文案（user / error）。余额不足不走这里。 */
export function pauseText(status: string, payload: Record<string, unknown> = {}): string {
  if (status === 'paused_insufficient_quota') {
    const need = Number(payload.needed ?? 0);
    return need > 0 ? `余额不足，这次提问大约需要 ${need}。` : '余额不足，这次提问没有开始。';
  }
  if (status === 'paused_input') return '任务在等待你的补充输入，回答后从断点继续（已完成步骤不重跑）';
  if (status === 'paused_budget') return '已达单任务 token 上限，任务已暂停。可继续（重置预算）或放弃本轮';
  if (status === 'paused_user') return '任务已按你的要求暂停，可点「继续」重跑';
  if (status === 'paused_error' || status === 'failed') return '任务中途出错已暂停，可点「重试」';
  return '任务已暂停';
}
