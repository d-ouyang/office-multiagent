// 与后端 core/events.py 的协议一一对应（§15.1）。改字段两边同步。
export type EventType =
  | 'thinking_delta'
  | 'content_delta'
  | 'tool_call_start'
  | 'tool_call_end'
  | 'observation'
  | 'status'
  | 'quota_paused'
  | 'artifact'
  | 'source'
  | 'error'
  | 'done'
  | 'task_summary'
  | 'context_usage'
  | 'visual'
  | 'ask_user'
  // v2.4.5：流式心跳（首 token 前/长思考期间每 3s），只用于"已等待 Ns"提示
  | 'heartbeat';

export interface StreamEvent {
  type: EventType;
  run_id: string;
  turn_id: string;
  seq: number;
  ts: number;
  data: Record<string, unknown>;
}
