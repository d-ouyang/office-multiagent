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
  const qs = ask?.questions ?? []; // 防御：旧格式/缺 questions 时不崩，渲染空态
  const total = qs.length;
  const [idx, setIdx] = useState(0);
  const [answers, setAnswers] = useState<(string | null)[]>(() => qs.map(() => null));
  const [custom, setCustom] = useState<{ [k: number]: string }>({});
  const [customMode, setCustomMode] = useState<{ [k: number]: boolean }>({});
  const [pendingOpt, setPendingOpt] = useState<{ [k: number]: string }>({}); // 2.1.0：expects_text 题的预选选项
  const [files, setFiles] = useState<{ [k: number]: string[] }>({});
  const fileRef = useRef<HTMLInputElement | null>(null);

  const q: AskQuestion = qs[Math.min(idx, total - 1)];
  const answer = answers[idx] ?? null;
  const answered = (i: number) => answers[i] !== null;
  const last = idx === total - 1;
  const canSubmitCurrent = Boolean(answer) || Boolean((custom[idx] ?? '').trim()) || (files[idx]?.length ?? 0) > 0;

  // 2.1.0 定稿交互：单问题/最后一题答完【自动进入续跑】（无确认按钮）；
  // 多题中间跳过/选择即翻页并记住（（跳过）会如实告知模型）。
  // 唯一例外：need_file 题答案声称要上传但没传 → 挂在本题等上传（上传完成自动续跑）。
  const tryAutoSubmit = (nextAnswers: (string | null)[], nextFiles: { [k: number]: string[] }) => {
    const pending = qs.some((item, i) => {
      const a = nextAnswers[i] ?? '';
      return item.need_file && a && /上传|文件/i.test(a) && !(nextFiles[i]?.length);
    });
    if (pending) return; // 停在本题，等上传
    const parts = qs.map((item, i) => {
      const a = nextAnswers[i] ?? '（跳过）';
      if (total === 1) return a === '（跳过）' ? '' : a;
      return `问题：${item.question}\n回答：${a}`;
    });
    const answer = total === 1 ? parts[0] : parts.join('\n\n');
    const attachments = Object.values(nextFiles).flat();
    onSubmit(answer, attachments);
  };

  const record = (value: string | null) => {
    const v = value ?? '（跳过）'; // 跳过也给模型明确信号，不是空字符串
    const next = [...answers];
    next[idx] = v;
    setAnswers(next);
    if (last || total === 1) {
      tryAutoSubmit(next, files);
      return;
    }
    setIdx((i) => Math.min(i + 1, total - 1));
  };

  // need_file 的题：答案声称要上传文件但实际没传 → 阻止提交（防"裸选上传选项"空跑）
  const pendingUpload = qs.some((item, i) => {
    const a = answers[i] ?? (i === idx ? (custom[idx] ?? '').trim() : '');
    return item.need_file && a && /上传|文件/i.test(a) && !(files[i]?.length);
  });

  const onPickFiles = async (list: FileList | null) => {
    if (!list) return;
    const nextFiles = { ...files };
    for (const file of Array.from(list)) {
      const name = await onUploadFile(file);
      if (name) nextFiles[idx] = [...(nextFiles[idx] ?? []), name];
    }
    setFiles(nextFiles);
    if (fileRef.current) fileRef.current.value = '';
    // 上传完成：本题答案若在等文件 → 自动进入续跑
    tryAutoSubmit(answers, nextFiles);
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
              onClick={() => {
                const needsText = q.expects_text || /自定义|我来补充|我来填|补充具体|其他范围/.test(opt);
                if (needsText) {
                  // 2.1.0：该题需要文本补充（如"自定义时间区间"）——选选项只预选，
                  // 强制展开输入框，填了具体值才 record 进入下一题（实测踩过：
                  // 选完直接过，日期缺失，模型等于没收到答案又问一遍）
                  setPendingOpt((prev) => ({ ...prev, [idx]: opt }));
                  setCustomMode((prev) => ({ ...prev, [idx]: true }));
                  return;
                }
                record(opt);
              }}
            >
              <span className="ask-option-num">{i + 1}</span>
              <span className="ask-option-text">
                {/* 提示词禁令的界面兜底：剥掉英文标识符括号技术注释（"销售额（sum_pay）"→"销售额"），保留"（推荐）"等中文 */}
                {opt.replace(/（[a-zA-Z_][a-zA-Z0-9_.]*）/g, '').replace(/\([^)]*[a-zA-Z_][a-zA-Z0-9_]*\)/g, '').trim()}
              </span>
              {q.expects_text && answer === opt && (
                <span className="ask-option-need" aria-label="该选项需要补充文本">需补充</span>
              )}
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
            placeholder={pendingOpt[idx] ? `${pendingOpt[idx]}：请补充具体内容（必填）` : '输入你的回答…'}
            aria-label="其他补充"
            onChange={(e) => setCustom((prev) => ({ ...prev, [idx]: e.target.value }))}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (custom[idx] ?? '').trim()) {
                e.preventDefault();
                const pre = pendingOpt[idx] ? `${pendingOpt[idx]}：` : '';
                record(pre + (custom[idx] ?? '').trim());
              }
            }}
          />
          <button
            type="button"
            className="admin-btn"
            disabled={!(custom[idx] ?? '').trim()}
            onClick={() => {
              const pre = pendingOpt[idx] ? `${pendingOpt[idx]}：` : '';
              record(pre + (custom[idx] ?? '').trim());
            }}
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
      {pendingUpload && (
        <div className="ask-files err">选了要上传文件但还没传——请先点上方选择文件，或改选其他选项。</div>
      )}

      <div className="ask-foot">
        <button
          type="button"
          className="admin-btn ghost"
          title="本题不留回答，模型将自行判断"
          onClick={() => record(null)}
        >
          跳过此题
        </button>
      </div>
      <div className="ask-hint">每题答完自动进入下一题；全部答完后任务自动从断点继续（已完成步骤不重跑）。</div>
    </div>
  );
}
