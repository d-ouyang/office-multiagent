// 2.1.0 P1-1 HITL：任务中补充输入卡片。
// 模型调 ask_user 后任务进入 paused_input，此卡片负责收集回答：
// 选项按钮（可多选一）+ 自由文本 + 文件上传（need_file 时），提交后断点续跑。
import { useRef, useState } from 'react';

import type { AskUserPayload } from '../lib/derive';

export default function AskUserCard({
  ask,
  uploading,
  uploadError,
  onUploadFile,
  onSubmit,
}: {
  ask: AskUserPayload;
  uploading?: boolean;
  uploadError?: string | null;
  /** 选中某选项（不传自由文本时以选项作为回答） */
  onSubmit: (answer: string, attachments: string[]) => void;
  /** 上传单个文件，返回服务端 file_name（复用聊天区上传管道） */
  onUploadFile: (file: File) => Promise<string | null>;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [text, setText] = useState('');
  const [files, setFiles] = useState<string[]>([]);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const canSubmit = Boolean(text.trim() || selected || files.length);

  const pickOption = (opt: string) => {
    setSelected((prev) => (prev === opt ? null : opt));
    setText('');
  };

  const onPickFiles = async (list: FileList | null) => {
    if (!list) return;
    for (const file of Array.from(list)) {
      const name = await onUploadFile(file);
      if (name) setFiles((prev) => [...prev, name]);
    }
    if (fileRef.current) fileRef.current.value = '';
  };

  const submit = () => {
    if (!canSubmit) return;
    const answer = text.trim() || selected || '';
    onSubmit(answer, files);
  };

  return (
    <div className="banner warn pause-banner ask-user-card" data-testid="ask-user-card">
      <div className="ask-question">
        <span aria-hidden>❓</span>
        <span>{ask.question}</span>
      </div>
      {ask.file_hint && <div className="ask-hint">文件要求：{ask.file_hint}</div>}
      {ask.options.length > 0 && (
        <div className="ask-options" role="group" aria-label="候选选项">
          {ask.options.map((opt) => (
            <button
              key={opt}
              type="button"
              className={`admin-btn${selected === opt ? '' : ' ghost'}`}
              aria-pressed={selected === opt}
              onClick={() => pickOption(opt)}
            >
              {opt}
            </button>
          ))}
        </div>
      )}
      <div className="ask-input-row">
        <input
          type="text"
          value={text}
          placeholder={ask.need_file ? '可先上传文件，再补充说明…' : '输入你的回答…'}
          aria-label="补充输入"
          onChange={(e) => {
            setText(e.target.value);
            if (e.target.value) setSelected(null);
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        {ask.need_file && (
          <input
            ref={fileRef}
            type="file"
            aria-label="上传文件"
            disabled={uploading}
            onChange={(e) => void onPickFiles(e.target.files)}
          />
        )}
        <button type="button" className="admin-btn" disabled={!canSubmit || uploading} onClick={submit}>
          提交并继续
        </button>
      </div>
      {files.length > 0 && <div className="ask-files">已上传：{files.join('、')}</div>}
      {uploadError && <div className="ask-files err">{uploadError}</div>}
      <div className="ask-hint">提交后任务从断点继续，已完成的步骤不会重跑。</div>
    </div>
  );
}
