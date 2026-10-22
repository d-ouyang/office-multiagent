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
  | 'context_usage';

export interface StreamEvent {
  type: EventType;
  run_id: string;
  turn_id: string;
  seq: number;
  ts: number;
  data: Record<string, unknown>;
}
