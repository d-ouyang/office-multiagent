// 通用确认弹窗（p6.28d）：参考 RAG 管理端 ConfirmDialog 的交互（一次挂载、全局可用），
// 这里做成受控组件：传 title/text/confirmText/danger + onConfirm/onCancel。
// 用途：代续跑这类"点了就花钱/就重跑"的操作必须先讲清楚再动手。
import { useEffect } from 'react';

export interface ConfirmSpec {
  title: string;
  text?: string;
  /** 补充说明列表（每条一行，比一长段文字可读） */
  bullets?: string[];
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
  /** 退出登录这类确认用浅红色，避免和删除一样重。 */
  dangerSoft?: boolean;
}

export default function ConfirmDialog({
  spec,
  busy = false,
  onConfirm,
  onCancel,
}: {
  spec: ConfirmSpec | null;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  useEffect(() => {
    if (!spec) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) onCancel();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [spec, busy, onCancel]);

  if (!spec) return null;
  return (
    <div className="ui-confirm-mask" onClick={() => !busy && onCancel()}>
      <div
        className="ui-confirm"
        role="alertdialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <h3>{spec.title}</h3>
        {spec.text && <p className="ui-confirm-text">{spec.text}</p>}
        {spec.bullets && spec.bullets.length > 0 && (
          <ul className="ui-confirm-bullets">
            {spec.bullets.map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
        )}
        <div className="ui-confirm-actions">
          <button type="button" className="admin-btn ghost" disabled={busy} onClick={onCancel}>
            {spec.cancelText ?? '取消'}
          </button>
          <button
            type="button"
            className={`admin-btn ${spec.dangerSoft ? 'danger-soft' : spec.danger ? 'danger' : ''}`}
            disabled={busy}
            onClick={onConfirm}
          >
            {busy ? '执行中…' : spec.confirmText ?? '确认'}
          </button>
        </div>
      </div>
    </div>
  );
}
