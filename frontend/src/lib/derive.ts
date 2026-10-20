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
