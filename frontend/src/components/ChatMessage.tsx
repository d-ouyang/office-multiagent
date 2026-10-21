// 聊天消息气泡（p6.2→p6.10）：用户右侧短气泡（hover 可编辑/复制）；助手左侧 =
// 深度思考折叠 + 步骤折叠 + markdown 正文（打字机）+ hover 复制。
// 交互对齐 RAG：user 消息编辑→回填输入框重发；assistant 复制→剪贴板 markdown 原文。
import { useState } from 'react';

import type { StreamEvent } from '../types';
import type { ToolCall } from '../lib/derive';
import { deriveContent, deriveFailure, deriveThinking, deriveToolCalls } from '../lib/derive';
import MarkdownView from './MarkdownView';
import { StepsPanel, ThinkingPanel } from './FoldPanels';

export interface ChatMessageData {
  role: 'user' | 'assistant';
  text?: string; // user 消息文本
  attachments?: string[]; // p6.12：随消息附件名（显示 chip；后端已单独注入 prompt）
  content?: string; // assistant 历史终答（p6.2c：历史只存终答，无事件流）
  events?: StreamEvent[]; // assistant 事件流（当前流或已固化）
  streaming?: boolean;
}

function CopyButton({ getText, label = '复制' }: { getText: () => string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      className="msg-action"
      title={label}
      onClick={() => {
        navigator.clipboard
          .writeText(getText())
          .then(() => {
            setDone(true);
            setTimeout(() => setDone(false), 1500);
          })
          .catch(() => {});
      }}
    >
      {done ? '已复制' : label}
    </button>
  );
}

export function ChatMessage({ msg, onEdit }: { msg: ChatMessageData; onEdit?: (text: string) => void }) {
  if (msg.role === 'user') {
    return (
      <div className="msg-row user">
        <div className="bubble user-bubble">
          {msg.attachments && msg.attachments.length > 0 && (
            <div className="msg-attachments">
              {msg.attachments.map((n) => (
                <span key={n} className="attach-chip static">
                  📎 {n}
                </span>
              ))}
            </div>
          )}
          {msg.text}
          {!msg.streaming && (
            <span className="msg-actions">
              {onEdit && (
                <button className="msg-action" title="编辑并重新发送" onClick={() => onEdit(msg.text ?? '')}>
                  编辑
                </button>
              )}
              <CopyButton getText={() => msg.text ?? ''} />
            </span>
          )}
        </div>
      </div>
    );
  }
  // 历史消息（无事件流）：直接渲染终答 markdown
  if (!msg.events) {
    return (
      <div className="msg-row assistant">
        <div className="assistant-block">
          <MarkdownView text={msg.content ?? ''} streaming={false} />
          <span className="msg-actions">
            <CopyButton getText={() => msg.content ?? ''} />
          </span>
        </div>
      </div>
    );
  }
  const events = msg.events;
  const thinking = deriveThinking(events);
  const toolCalls: ToolCall[] = deriveToolCalls(events);
  const content = deriveContent(events);
  const failure = deriveFailure(events); // p6.12b：失败/暂停专门展示（持久化——events 已随消息固化）
  return (
    <div className="msg-row assistant">
      <div className="assistant-block">
        <ThinkingPanel text={thinking} streaming={!!msg.streaming} />
        <StepsPanel toolCalls={toolCalls} streaming={!!msg.streaming} />
        {failure && (
          <div className={`msg-failure ${failure.kind}`}>
            <span className="failure-icon">{failure.kind === 'quota' ? '⏸' : '⚠'}</span>
            <span>
              <b>{failure.title}</b>：{failure.reason}
              {failure.kind === 'quota' && failure.balance != null && (
                <>（当前余额 {failure.balance.toLocaleString()}，本次需要 {failure.needed != null ? failure.needed.toLocaleString() : '-'}）</>
              )}
              {failure.kind === 'quota' && <>——充值/恢复余额后重新发送即可</>}
              {failure.kind === 'error' && failure.code && <>（code: {failure.code}）</>}
            </span>
          </div>
        )}
        {content && <MarkdownView text={content} streaming={msg.streaming} />}
        {msg.streaming && !content && !failure && <div className="typing">正在思考…</div>}
        {!msg.streaming && content && (
          <span className="msg-actions">
            <CopyButton getText={() => content} />
          </span>
        )}
      </div>
    </div>
  );
}

export default ChatMessage;
