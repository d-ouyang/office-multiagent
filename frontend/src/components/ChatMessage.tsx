// 用户消息：气泡下方是提问时间，hover 出编辑/复制图标。
// 助手消息：正文下方独立一行——复制、点赞、点踩、用量、模型、时间、耗时。
// 点赞/点踩 v2.0.0-p2.2 起闭环入库：激活态实心；点踩必走弹窗（原因多选/其他原因）；
// 再点实心图标 = 取消；二次点踩回显已选原因、提交后覆盖（旧信息保留在服务端流水）。
import { lazy, useEffect, useRef, useState, type ReactNode } from 'react';
import { Copy, Pencil, ThumbsDown, ThumbsUp } from 'lucide-react';

import type { FeedbackRating, MessageFeedback } from '../lib/api';
import type { StreamEvent } from '../types';
import { deriveArtifacts, deriveFailure, deriveProcess, deriveReplyMeta } from '../lib/derive';
import { FeedbackDialog } from './FeedbackDialog';
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
  /** 后端消息 id（p2.1 列表带出）——有 id 才能反馈闭环 */
  id?: number;
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
  /** 反馈当前态（p2.1 消息列表带出；切换会话后激活态仍在） */
  feedback?: MessageFeedback | null;
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
  anchorId,
  located,
  onEditSubmit,
  onPreview,
  onFeedbackSubmit,
  onFeedbackCancel,
}: {
  msg: ChatMessageData;
  index: number;
  anchorId?: string;
  located?: boolean;
  onEditSubmit?: (index: number, text: string, paths: string[]) => boolean | void | Promise<boolean | void>;
  onPreview?: (path: string) => void;
  /** v2.0.0-p2.2：提交/覆盖反馈。成功返回最新当前态，失败返回 null。 */
  onFeedbackSubmit?: (
    messageId: number,
    rating: FeedbackRating,
    tags: string[],
    comment: string,
  ) => Promise<MessageFeedback | null>;
  /** v2.0.0-p2.2：取消反馈。成功返回 true。 */
  onFeedbackCancel?: (messageId: number) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(msg.text ?? '');
  const [paths, setPaths] = useState<string[]>(msg.attachmentPaths ?? []);
  const [feedback, setFeedback] = useState<MessageFeedback | null>(msg.feedback ?? null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [fbBusy, setFbBusy] = useState(false);
  // p2.11 节流（两层）：ref 在途锁拦"请求没回来就再点"；冷却锁拦"请求刚好
  // 完成、下一次点击又立即发出"——线上实测请求往返 ~100ms 比连点间隔还快，
  // 只有在途锁时 6 连点会发出 6 个合法但无意义的翻转请求。
  const fbBusyRef = useRef(false);
  const fbCooldownRef = useRef(0);
  const [fbError, setFbError] = useState<string | null>(null);

  // 只在「换消息」（id 变化）时按服务端当前态复位。
  // p2.8：不能把 msg.feedback 放进依赖——提交成功后本地已乐观更新，而父级的
  // messages 要等回调里才同步；期间任何父级重渲染都会把激活态打回旧值
  //（症状：点赞成功后图标闪一下又变空心）。服务端真相由父级在提交/取消
  // 成功后写回 msg.feedback（与本地位一致），这里只负责换消息复位。
  useEffect(() => {
    setFeedback(msg.feedback ?? null);
  }, [msg.id]);

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
      <div className={`msg-row user${located ? ' located' : ''}`} id={anchorId} data-question={msg.text || ''}>
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
  // 2.1.0：交付物暂存——流式期间与挂起/失败中间态不显示，任务终态 done 后统一展示
  // （用户反馈：中途产物一直挂在对话框最下面，等完全回复之后再显示）
  const finalStatus = events
    ? (() => {
        for (let i = events.length - 1; i >= 0; i -= 1) {
          const e = events[i];
          if (e.type === 'done') return String(e.data?.status ?? '');
        }
        return null;
      })()
    : null;
  // ⚠️ done 事件的 data.status 是【路由值】（single/multi），不是任务状态——
  // 上一版用 finalStatus==='done' 判定导致交付物永远不显示（实测踩过）。
  // 正确判定：非流式中 且 done 状态不是暂停/失败中间态 → 显示交付物。
  const showDeliverables =
    !msg.streaming && (finalStatus === null || !finalStatus.startsWith('paused'));
  const artifacts = events && showDeliverables ? deriveArtifacts(events) : [];
  // 2.1.0 定稿：图表/流程图改为过程时间线内实时渲染（ProcessTrace visual 项），
  // 消息级不再渲染 visual——最终回答不重复显示图。底部只保留文件级 artifacts。
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

  // v2.0.0-p2.2 状态机（PLAN §4.1）：激活态再点 = 取消；点赞直接落库；
  // 点踩（无论当前态）都走弹窗，提交后覆盖。
  // p2.8：乐观更新（点击立即变实心，失败回滚）+ ref 节流（防暴力点击）——
  // 节流必须用 ref 而非 state：同一渲染批次内的连点读到的还是旧闭包值，
  // state guard 会被击穿；ref 置位是同步的，跨批次/同批次都拦得住。
  // 2.1.0：挂起中间态（HITL/预算暂停）的消息是"半截对话"，反馈没有意义——隐藏
  const canFeedback =
    !!(msg.id && onFeedbackSubmit && onFeedbackCancel) &&
    !(finalStatus === 'paused_input' || finalStatus === 'paused_budget');
  const rating = feedback?.rating ?? null;
  const fbThrottled = () =>
    fbBusyRef.current || Date.now() - fbCooldownRef.current < 400;
  const submitFeedback = async (r: FeedbackRating, tags: string[], comment: string) => {
    if (!msg.id || !onFeedbackSubmit || fbThrottled()) return false;
    const prev = feedback;
    fbBusyRef.current = true;
    setFbBusy(true);
    setFbError(null);
    setFeedback({ rating: r, tags, comment: comment || null, at: null }); // 乐观
    try {
      const state = await onFeedbackSubmit(msg.id, r, tags, comment);
      if (state) {
        setFeedback(state); // 以服务端回执为准（含 at 时间戳）
        return true;
      }
      setFeedback(prev); // 回执异常：回滚乐观态
      return false;
    } catch (e) {
      setFeedback(prev);
      setFbError((e as Error).message);
      return false;
    } finally {
      fbBusyRef.current = false;
      fbCooldownRef.current = Date.now();
      setFbBusy(false);
    }
  };
  const cancelFeedback = async () => {
    if (!msg.id || !onFeedbackCancel || fbThrottled()) return;
    const prev = feedback;
    fbBusyRef.current = true;
    setFbBusy(true);
    setFbError(null);
    setFeedback(null); // 乐观
    try {
      if (!(await onFeedbackCancel(msg.id))) setFeedback(prev);
    } catch (e) {
      setFeedback(prev);
      setFbError((e as Error).message);
    } finally {
      fbBusyRef.current = false;
      fbCooldownRef.current = Date.now();
      setFbBusy(false);
    }
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
            {canFeedback && (
              <>
                <IconTip
                  label={rating === 'like' ? '取消点赞' : '点赞'}
                  pressed={rating === 'like'}
                  onClick={() => (rating === 'like' ? void cancelFeedback() : void submitFeedback('like', [], ''))}
                >
                  <ThumbsUp size={15} strokeWidth={1.8} />
                </IconTip>
                <IconTip
                  label={rating === 'dislike' ? '取消点踩' : '点踩'}
                  pressed={rating === 'dislike'}
                  onClick={() => (rating === 'dislike' ? void cancelFeedback() : setDialogOpen(true))}
                >
                  <ThumbsDown size={15} strokeWidth={1.8} />
                </IconTip>
              </>
            )}
            <span className="reply-stats">
              <span className="reply-tokens">
                <span>
                  {finalStatus === 'paused_input' || finalStatus === 'paused_budget'
                    ? '⏸ 任务未完结（等待你的输入/选择后从断点继续）'
                    : `共消耗 ${formatTokens(tokens)}`}
                </span>
                {meta.steps && meta.steps.length > 0 && (
                  <span className="token-pop" role="tooltip">
                    <span className="token-pop__head">逐步用量</span>
                    {meta.steps.map((s, i) => (
                      <span key={i} className="token-pop__row">
                        <span className="token-pop__label">{s.label}</span>
                        <span className="token-pop__num">{formatTokens(s.tokens)}</span>
                      </span>
                    ))}
                  </span>
                )}
              </span>
              <span className="reply-model">{modelDisplayName(modelId)}</span>
              {clock && <span>{clock}</span>}
              <span>耗时 {formatDuration(meta.durationMs)}</span>
            </span>
          </div>
        )}
        {/* p2.8：点赞/取消失败时（弹窗未开）就地提示，错误不该只有弹窗路径可见 */}
        {!msg.streaming && fbError && !dialogOpen && (
          <div className="fb-error" role="alert">{fbError}</div>
        )}
        {canFeedback && (
          <FeedbackDialog
            open={dialogOpen}
            busy={fbBusy}
            error={fbError}
            onClose={() => {
              setDialogOpen(false);
              setFbError(null);
            }}
            onSubmit={(tags, comment) => submitFeedback('dislike', tags, comment)}
          />
        )}
      </div>
    </div>
  );
}

export default ChatMessage;
