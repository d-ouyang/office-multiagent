// 2.1.0 P1-1 HITL：任务中补充输入向导（参考 WorkBuddy 交互）。
// 一次 ask_user 可携带多个问题：标题 + n/N 翻页 + 编号选项（点选即进下一题）
// + ✏️其他补充 + 跳过；全部答完后一次性提交 → POST /answer 断点续跑。
// 交互过程（答到第几题）不落库——切会话回来从头交互，与挂起点语义一致。
import { useRef, useState } from 'react';

import type { AskQuestion, AskUserPayload } from '../lib/derive';

export default function AskUserCard({
  ask,
  uploadError,
  onUploadFile,
  onSubmit,
  onDismiss,
}: {
  ask: AskUserPayload;
  uploadError?: string | null;
  /** 上传单个文件，返回服务端 file_name（复用聊天区上传管道） */
  onUploadFile: (file: File) => Promise<string | null>;
  onSubmit: (answer: string, attachments: string[]) => void;
  onDismiss: () => void;
}) {
  const qs = ask.questions;
  const total = qs.length;
  const [idx, setIdx] = useState(0);
  const [answers, setAnswers] = useState<(string | null)[]>(() => qs.map(() => null));
  const [custom, setCustom] = useState<{ [k: number]: string }>({});
  const [customMode, setCustomMode] = useState<{ [k: number]: boolean }>({});
  const [files, setFiles] = useState<{ [k: number]: string[] }>({});
  const fileRef = useRef<HTMLInputElement | null>(null);

  const q: AskQuestion = qs[Math.min(idx, total - 1)];
  const answer = answers[idx] ?? null;
  const answered = (i: number) => answers[i] !== null;
  const allDone = answers.every((a) => a !== null);
  const last = idx === total - 1;

  const record = (value: string | null) => {
    const v = value ?? '（跳过）'; // 跳过也给模型明确信号，不是空字符串
    const next = [...answers];
    next[idx] = v;
    setAnswers(next);
    if (total === 1) {
      // 单问题：答完即提交（含跳过）
      onSubmit(v, Object.values(files).flat());
      return;
    }
    if (!last) setIdx((i) => Math.min(i + 1, total - 1));
  };

  const submitAll = () => {
    // 未作答的题按「跳过」处理；多问题时按 Q/A 段落聚合，单问题直接给答案文本
    const parts = qs.map((item, i) => {
      const a = answers[i] ?? '（跳过）';
      if (total === 1) return a === '（跳过）' ? '' : a;
      return `问题：${item.question}\n回答：${a}`;
    });
    const answer = total === 1 ? parts[0] : parts.join('\n\n');
    const attachments = Object.values(files).flat();
    onSubmit(answer, attachments);
  };

  const onPickFiles = async (list: FileList | null) => {
    if (!list) return;
    for (const file of Array.from(list)) {
      const name = await onUploadFile(file);
      if (name) setFiles((prev) => ({ ...prev, [idx]: [...(prev[idx] ?? []), name] }));
    }
    if (fileRef.current) fileRef.current.value = '';
  };

  return (
    <div className="banner warn pause-banner ask-user-card" data-testid="ask-user-card">
      <div className="ask-head">
        <span className="ask-title">{q.question}</span>
        <span className="ask-nav">
          {total > 1 && (
            <>
              <button
                type="button"
                className="admin-btn ghost"
                aria-label="上一题"
                disabled={idx === 0}
                onClick={() => setIdx((i) => Math.max(0, i - 1))}
              >
                ‹
              </button>
              <span className="ask-progress">
                {idx + 1}/{total}
              </span>
              <button
                type="button"
                className="admin-btn ghost"
                aria-label="下一题"
                disabled={idx >= total - 1}
                onClick={() => setIdx((i) => Math.min(total - 1, i + 1))}
              >
                ›
              </button>
            </>
          )}
          <button type="button" className="admin-btn ghost" aria-label="收起" onClick={onDismiss}>
            ✕
          </button>
        </span>
      </div>

      {q.options.length > 0 && (
        <div className="ask-options" role="group" aria-label="候选选项">
          {q.options.map((opt, i) => (
            <button
              key={opt}
              type="button"
              className={`ask-option${answer === opt ? ' active' : ''}`}
              aria-pressed={answer === opt}
              onClick={() => record(opt)}
            >
              <span className="ask-option-num">{i + 1}</span>
              <span className="ask-option-text">{opt}</span>
            </button>
          ))}
        </div>
      )}

      {customMode[idx] ? (
        <div className="ask-option active ask-custom">
          <span className="ask-option-num" aria-hidden>
            ✏️
          </span>
          <input
            type="text"
            autoFocus
            value={custom[idx] ?? ''}
            placeholder="输入你的回答…"
            aria-label="其他补充"
            onChange={(e) => setCustom((prev) => ({ ...prev, [idx]: e.target.value }))}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (custom[idx] ?? '').trim()) {
                e.preventDefault();
                record((custom[idx] ?? '').trim());
              }
            }}
          />
          <button
            type="button"
            className="admin-btn"
            disabled={!(custom[idx] ?? '').trim()}
            onClick={() => record((custom[idx] ?? '').trim())}
            aria-label="确认补充"
          >
            →
          </button>
        </div>
      ) : (
        <button
          type="button"
          className="ask-option ask-custom-toggle"
          onClick={() => setCustomMode((prev) => ({ ...prev, [idx]: true }))}
        >
          <span className="ask-option-num" aria-hidden>
            ✏️
          </span>
          <span className="ask-option-text">其他补充…</span>
        </button>
      )}

      {q.need_file && (
        <div className="ask-file-row">
          <input
            ref={fileRef}
            type="file"
            aria-label="上传文件"
            onChange={(e) => void onPickFiles(e.target.files)}
          />
          <span className="ask-file-hint">{q.file_hint || '支持 csv / xlsx'}</span>
        </div>
      )}
      {(files[idx]?.length ?? 0) > 0 && (
        <div className="ask-files">已上传：{(files[idx] ?? []).join('、')}</div>
      )}
      {uploadError && <div className="ask-files err">{uploadError}</div>}

      <div className="ask-foot">
        <button type="button" className="admin-btn ghost" onClick={() => record(null)}>
          跳过
        </button>
        {last && allDone && (
          <button type="button" className="admin-btn" onClick={submitAll}>
            提交并继续
          </button>
        )}
        {!last && answered(idx) && (
          <button type="button" className="admin-btn" onClick={() => setIdx((i) => Math.min(total - 1, i + 1))}>
            下一题
          </button>
        )}
      </div>
      <div className="ask-hint">全部回答完成后一次性提交，任务从断点继续（已完成步骤不重跑）。</div>
    </div>
  );
}
