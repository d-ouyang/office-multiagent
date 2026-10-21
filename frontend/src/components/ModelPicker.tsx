// 模型切换器（p6.2/p6.8）：从 /models 拉对话模型下拉。
// p6.8：按渠道分组（DeepSeek 官方 / 硅基流动）、option 带上下文/能力标签、
// 选中变化回调上层（PATCH 当前会话默认模型 + 信息条展示）。
import { useEffect, useState } from 'react';

interface DialogueModel {
  id: string;
  name: string;
  provider: string;
  multimodal_input: boolean;
  context_window: number;
  supports_reasoning: boolean;
  description: string;
}

const PROVIDER_LABEL: Record<string, string> = {
  deepseek: 'DeepSeek 官方',
  siliconflow: '硅基流动',
};

function fmtCtx(n: number): string {
  if (n >= 1_000_000) return `${Math.round(n / 1_000_000)}M`;
  if (n >= 1000) return `${Math.round(n / 1000)}K`;
  return String(n);
}

function optionLabel(m: DialogueModel): string {
  const tags: string[] = [];
  if (m.supports_reasoning) tags.push('思考');
  if (m.multimodal_input) tags.push('视觉');
  return `${m.name}（${fmtCtx(m.context_window)}${tags.length ? ' · ' + tags.join('/') : ''}）`;
}

export function ModelPicker({ onChange }: { onChange?: (m: DialogueModel | null) => void }) {
  const [models, setModels] = useState<DialogueModel[]>([]);
  const [current, setCurrent] = useState<string>(localStorage.getItem('office_model') ?? '');

  useEffect(() => {
    fetch('/api/v1/models')
      .then((r) => r.json())
      .then((d) => setModels(d.models ?? []))
      .catch(() => setModels([]));
  }, []);

  if (!models.length) return null;
  const groups = [...new Set(models.map((m) => m.provider))];

  return (
    <select
      className="model-picker"
      value={current}
      title="模型切换（当前会话默认模型）"
      onChange={(e) => {
        setCurrent(e.target.value);
        localStorage.setItem('office_model', e.target.value);
        onChange?.(models.find((m) => m.id === e.target.value) ?? null);
      }}
    >
      <option value="">默认模型（DeepSeek V3 · 官方）</option>
      {groups.map((p) => (
        <optgroup key={p} label={PROVIDER_LABEL[p] ?? p}>
          {models
            .filter((m) => m.provider === p)
            .map((m) => (
              <option key={m.id} value={m.id}>
                {optionLabel(m)}
              </option>
            ))}
        </optgroup>
      ))}
    </select>
  );
}

export default ModelPicker;
