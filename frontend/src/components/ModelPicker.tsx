// 模型切换器（p6.2/p6.5）：从 /models（公开）拉对话模型下拉。
// p6.5：选中即存 localStorage + 回调上层（PATCH 当前会话默认模型，后端任务按它执行）。
import { useEffect, useState } from 'react';

interface DialogueModel {
  id: string;
  name: string;
}

export function ModelPicker({ onChange }: { onChange?: (modelId: string) => void }) {
  const [models, setModels] = useState<DialogueModel[]>([]);
  const [current, setCurrent] = useState<string>(localStorage.getItem('office_model') ?? '');

  useEffect(() => {
    fetch('/api/v1/models')
      .then((r) => r.json())
      .then((d) => setModels(d.models ?? []))
      .catch(() => setModels([]));
  }, []);

  if (!models.length) return null;
  return (
    <select
      className="model-picker"
      value={current}
      title="模型切换（当前会话默认模型）"
      onChange={(e) => {
        setCurrent(e.target.value);
        localStorage.setItem('office_model', e.target.value);
        onChange?.(e.target.value);
      }}
    >
      <option value="">默认模型</option>
      {models.map((m) => (
        <option key={m.id} value={m.id}>
          {m.name}
        </option>
      ))}
    </select>
  );
}

export default ModelPicker;
