// 聊天消息气泡（p6.2）：用户右侧短气泡；助手左侧 = 深度思考折叠 + 步骤折叠 + markdown 正文（打字机）。
import type { StreamEvent } from '../types';
import type { ToolCall } from '../lib/derive';
import { deriveContent, deriveThinking, deriveToolCalls } from '../lib/derive';
import MarkdownView from './MarkdownView';
import { StepsPanel, ThinkingPanel } from './FoldPanels';

export interface ChatMessageData {
  role: 'user' | 'assistant';
  text?: string; // user 消息文本
  events?: StreamEvent[]; // assistant 事件流（当前流或已固化）
  streaming?: boolean;
}

export function ChatMessage({ msg }: { msg: ChatMessageData }) {
  if (msg.role === 'user') {
    return (
      <div className="msg-row user">
        <div className="bubble user-bubble">{msg.text}</div>
      </div>
    );
  }
  const events = msg.events ?? [];
  const thinking = deriveThinking(events);
  const toolCalls: ToolCall[] = deriveToolCalls(events);
  const content = deriveContent(events);
  return (
    <div className="msg-row assistant">
      <div className="assistant-block">
        <ThinkingPanel text={thinking} streaming={!!msg.streaming} />
        <StepsPanel toolCalls={toolCalls} streaming={!!msg.streaming} />
        {content && <MarkdownView text={content} streaming={msg.streaming} />}
        {msg.streaming && !content && <div className="typing">正在思考…</div>}
      </div>
    </div>
  );
}

export default ChatMessage;
