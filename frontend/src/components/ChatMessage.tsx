// 用户消息：气泡下方是提问时间，hover 出编辑/复制图标。
// 助手消息：正文下方独立一行——复制、点赞、点踩、用量、模型、时间、耗时。
// 点赞/点踩只留在这次渲染里，不入库。
import { lazy, Suspense, useState, type ReactNode } from 'react';
import { Copy, Pencil, ThumbsDown, ThumbsUp } from 'lucide-react';

import type { StreamEvent } from '../types';
import { deriveArtifacts, deriveFailure, deriveProcess, deriveReplyMeta, deriveVisuals } from '../lib/derive';
import { FlowChart } from './FlowChart';
import type { ChartSpec } from './ChartView';
import type { FlowSpec } from '../lib/flowLayout';
import { formatClock, formatDuration, formatTokens } from '../lib/format';
import { modelDisplayName } from './ModelPicker';
import MarkdownView from './MarkdownView';
import { ProcessTrace } from './FoldPanels';

const ChartView = lazy(() => import('./ChartView').then((module) => ({ default: module.ChartView })));

export interface ChatMessageData {
  role: 'user' | 'assistant';
  text?: string;
  attachments?: string[];
  attachmentPaths?: string[];
  content?: string;
  events?: StreamEvent[];
  streaming?: boolean;
  createdAt?: number;
  /** 账本补上的模型 id（trace 的 done 事件没有 model 时用） */
  model?: string;
  tokens?: number;
}

function IconTip({
  label,
  pressed,
  onClick,
  children,
}: {
  label: string;
  pressed?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      className="icon-btn"
      data-tip={label}
      data-on={pressed ? '' : undefined}
      aria-label={label}
      aria-pressed={pressed}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function CopyIcon({ getText }: { getText: () => string }) {
  const [done, setDone] = useState(false);
  return (
    <IconTip
      label={done ? '已复制' : '复制'}
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
      <Copy size={15} strokeWidth={1.8} />
    </IconTip>
  );
}

export function ChatMessage({
  msg,
  index,
  onEditSubmit,
  onPreview,
}: {
  msg: ChatMessageData;
  index: number;
  onEditSubmit?: (index: number, text: string, paths: string[]) => boolean | void | Promise<boolean | void>;
  onPreview?: (path: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(msg.text ?? '');
  const [paths, setPaths] = useState<string[]>(msg.attachmentPaths ?? []);
  const [vote, setVote] = useState<'up' | 'down' | null>(null);

  const commitEdit = () => {
    if (!draft.trim() && paths.length === 0) return;
    void Promise.resolve(onEditSubmit?.(index, draft.trim(), paths)).then((ok) => {
      if (ok !== false) setEditing(false);
    });
  };

  if (msg.role === 'user') {
    const files = (msg.attachmentPaths?.length ? msg.attachmentPaths : msg.attachments) ?? [];
    const clock = formatClock(msg.createdAt);
    const fileButtons = files.map((p) => {
      const label = p.split('/').pop() || p;
      return (
        <button
          key={p}
          type="button"
          className="attach-chip"
          title="查看这份文件"
          onClick={() => onPreview?.(p)}
        >
          {label}
        </button>
      );
    });
    return (
      <div className="msg-row user">
        <div className="user-stack">
          {editing ? (
            <div className="user-edit">
              {paths.length > 0 && (
                <div className="msg-attachments">
                  <span className="attach-label">附带文件</span>
                  {paths.map((p) => (
                    <span key={p} className="attach-chip" title={p}>
                      <button type="button" className="attach-open" onClick={() => onPreview?.(p)}>
                        {p.split('/').pop() ?? p}
                      </button>
                      <button
                        type="button"
                        className="attach-remove"
                        aria-label={`移除 ${p}`}
                        onClick={() => setPaths((prev) => prev.filter((x) => x !== p))}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              )}
              <textarea
                className="user-edit-input"
                value={draft}
                aria-label="编辑提问"
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    commitEdit();
                  }
                  if (e.key === 'Escape') setEditing(false);
                }}
              />
              <div className="user-edit-foot">
                <span className="user-edit-hint">编辑后将从此处重新开始对话，产物也将回退至此信息前版本</span>
                <button type="button" className="ghost" onClick={() => setEditing(false)}>
                  取消
                </button>
                <button
                  type="button"
                  className="send"
                  disabled={!draft.trim() && paths.length === 0}
                  onClick={commitEdit}
                >
                  发送
                </button>
              </div>
            </div>
          ) : (
            <div className="bubble user-bubble">
              {msg.text}
              {files.length > 0 && (
                <div className="msg-attachments">
                  <span className="attach-label">附带文件</span>
                  {fileButtons}
                </div>
              )}
            </div>
          )}
          {!editing && (
            <div className="user-meta">
              {clock && <span className="msg-time">{clock}</span>}
              {onEditSubmit && (
                <IconTip
                  label="编辑"
                  onClick={() => {
                    setDraft(msg.text ?? '');
                    setPaths(msg.attachmentPaths ?? []);
                    setEditing(true);
                  }}
                >
                  <Pencil size={15} strokeWidth={1.8} />
                </IconTip>
              )}
              <CopyIcon getText={() => msg.text ?? ''} />
            </div>
          )}
        </div>
      </div>
    );
  }

  const events = msg.events;
  const process = events ? deriveProcess(events) : null;
  const artifacts = events ? deriveArtifacts(events) : [];
  const visuals = events ? deriveVisuals(events) : [];
  const content = process ? process.result : (msg.content ?? '');
  const failure = events ? deriveFailure(events) : null;
  const meta = events ? deriveReplyMeta(events) : {};
  const modelId = meta.model || msg.model;
  const tokens = meta.tokens ?? msg.tokens;
  const clock = formatClock(msg.createdAt || meta.endedAt);
  const copyText = () => {
    if (content) return content;
    if (failure) return `${failure.title}：${failure.reason}`;
    return msg.content ?? '';
  };

  return (
    <div className="msg-row assistant">
      <div className="assistant-block">
        {process && process.steps.length > 0 && (
          <ProcessTrace steps={process.steps} durationMs={process.durationMs ?? meta.durationMs} streaming={!!msg.streaming} />
        )}
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
        {visuals.map((item, index) => {
          if (item.kind === 'flow' && Array.isArray(item.nodes) && Array.isArray(item.edges) && Array.isArray(item.path)) {
            return <FlowChart key={`flow-${index}`} spec={item as unknown as FlowSpec} />;
          }
          if (item.kind === 'chart' && typeof item.chart === 'string') {
            return (
              <Suspense key={`chart-${index}`} fallback={<div className="chart-card">正在绘制图表…</div>}>
                <ChartView spec={item as unknown as ChartSpec} />
              </Suspense>
            );
          }
          return null;
        })}
        {artifacts.length > 0 && (
          <div className="msg-attachments">
            <span className="attach-label">生成文件</span>
            {artifacts.map((item) => (
              <button
                key={item.asset_id}
                type="button"
                className="attach-chip"
                onClick={() => onPreview?.(item.storage_url || item.name || '')}
              >
                {item.name || item.asset_id}
              </button>
            ))}
          </div>
        )}
        {msg.streaming && !content && !failure && <div className="typing">正在思考…</div>}
        {!msg.streaming && (
          <div className="reply-meta">
            <CopyIcon getText={copyText} />
            <IconTip
              label="点赞"
              pressed={vote === 'up'}
              onClick={() => setVote((v) => (v === 'up' ? null : 'up'))}
            >
              <ThumbsUp size={15} strokeWidth={1.8} />
            </IconTip>
            <IconTip
              label="点踩"
              pressed={vote === 'down'}
              onClick={() => setVote((v) => (v === 'down' ? null : 'down'))}
            >
              <ThumbsDown size={15} strokeWidth={1.8} />
            </IconTip>
            <span className="reply-stats">
              <span>共消耗 {formatTokens(tokens)}</span>
              <span className="reply-model">{modelDisplayName(modelId)}</span>
              {clock && <span>{clock}</span>}
              <span>耗时 {formatDuration(meta.durationMs)}</span>
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

export default ChatMessage;
