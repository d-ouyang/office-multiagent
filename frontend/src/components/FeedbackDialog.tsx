// 点踩弹窗（v2.0.0-p2.2，PLAN-2.0.0 §4.2）：抱歉话术 + 原因 tag 多选 +
// 「其他原因」展开多行输入（0/200）。遮罩点击不关闭（防误触丢填写），仅 X 关闭。
import { useEffect, useState } from 'react';
import { X } from 'lucide-react';

import { FEEDBACK_COMMENT_MAX, FEEDBACK_TAGS } from '../lib/api';

export function FeedbackDialog({
  open,
  initialTags,
  initialComment,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  open: boolean;
  initialTags?: string[];
  initialComment?: string;
  busy?: boolean;
  error?: string | null;
  onClose: () => void;
  /** 返回 true = 提交成功（组件关弹窗）；false/异常由调用方显示 error。 */
  onSubmit: (tags: string[], comment: string) => Promise<boolean>;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [comment, setComment] = useState('');

  useEffect(() => {
    if (open) {
      setSelected(initialTags ?? []);
      setComment(initialComment ?? '');
    }
  }, [open, initialTags, initialComment]);

  if (!open) return null;
  const canSubmit = !busy && (selected.length > 0 || comment.trim().length > 0);

  const toggle = (tag: string) => {
    setSelected((prev) => (prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]));
  };

  const submit = async () => {
    if (!canSubmit) return;
    const ok = await onSubmit(selected, comment.trim());
    if (ok) onClose();
  };

  return (
    <div className="fb-overlay" role="dialog" aria-label="意见反馈">
      <div className="fb-card">
        <header className="fb-head">
          <div>
            <h3 className="fb-title">抱歉，这次回答没能帮到你</h3>
            <p className="fb-sub">告诉我们哪里做得不好，我们会认真改进</p>
          </div>
          <button type="button" className="fb-close" aria-label="关闭" onClick={onClose}>
            <X size={18} strokeWidth={1.8} />
          </button>
        </header>
        <div className="fb-tags" role="group" aria-label="不满意的原因">
          {FEEDBACK_TAGS.map((tag) => (
            <button
              key={tag}
              type="button"
              className={`fb-tag${selected.includes(tag) ? ' on' : ''}`}
              aria-pressed={selected.includes(tag)}
              onClick={() => toggle(tag)}
            >
              {tag}
            </button>
          ))}
        </div>
        {selected.includes('其他原因') && (
          <div className="fb-other">
            <textarea
              className="fb-input"
              placeholder="请描述具体的原因"
              value={comment}
              maxLength={FEEDBACK_COMMENT_MAX}
              aria-label="其他原因"
              onChange={(e) => setComment(e.target.value)}
            />
            <span className="fb-count">{comment.length}/{FEEDBACK_COMMENT_MAX}</span>
          </div>
        )}
        {error && <p className="fb-error">{error}</p>}
        <button type="button" className="fb-submit" disabled={!canSubmit} onClick={() => void submit()}>
          {busy ? '提交中…' : '提交反馈'}
        </button>
      </div>
    </div>
  );
}

export default FeedbackDialog;
