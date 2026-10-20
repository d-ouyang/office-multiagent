// 模型切换器（p6.2）：从 /models（公开）拉对话模型下拉。
// 注意：选中值暂存 localStorage（office_model），后端 session.model 选择链路（§十三）是后续任务。
import { useEffect, useState } from 'react';

interface DialogueModel {
  id: string;
  name: string;
}

export function ModelPicker() {
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
      title="模型切换（选择跟随后续会话配置生效）"
      onChange={(e) => {
        setCurrent(e.target.value);
        localStorage.setItem('office_model', e.target.value);
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
