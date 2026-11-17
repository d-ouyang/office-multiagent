/**
 * 统一提示条（v2.4.1）。
 *
 * 为什么收拢：此前每个页面各自拼 `<div className="banner err">{string}</div>`，文案格式不一，
 * 且多半只有 `HTTP 429` 这种实现细节。现在统一由 `lib/apiError.describeError()` 产出
 * `{kind,title,message,hint}`，本组件只负责"按 kind 换样式、按字段排版"。
 *
 * 用法：
 *   <Notice notice={describeError(err)} onClose={() => setError(null)} />
 *   <Notice notice={{ kind: 'info', title: '文件已上传', message: 'big-doc.md · 93,041 字' }} />
 */
import type { NoticeCopy } from '../lib/apiError';

export interface NoticeProps {
  notice: NoticeCopy;
  onClose?: () => void;
  /** 可选操作按钮（如"去充值""重新登录"），不传就只显示文字 */
  action?: { label: string; onClick: () => void };
}

export default function Notice({ notice, onClose, action }: NoticeProps) {
  return (
    <div className={`notice notice-${notice.kind}`} role="alert">
      <span className="notice-mark" aria-hidden="true" />
      <div className="notice-body">
        <div className="notice-title">{notice.title}</div>
        {notice.message && <div className="notice-message">{notice.message}</div>}
        {notice.hint && <div className="notice-hint">{notice.hint}</div>}
        {action && (
          <button type="button" className="notice-action" onClick={action.onClick}>
            {action.label}
          </button>
        )}
      </div>
      {onClose && (
        <button type="button" className="notice-close" onClick={onClose} aria-label="关闭提示">
          ×
        </button>
      )}
    </div>
  );
}
