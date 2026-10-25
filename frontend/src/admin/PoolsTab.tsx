import { useCallback, useEffect, useMemo, useState } from 'react';

import Select from '../components/ui/Select';
import {
  adminCreatePool,
  adminDeletePool,
  adminModelPools,
  adminModelsCatalog,
  adminSavePoolModels,
  adminUpdateModel,
  type AdminModel,
  type ModelPool,
} from '../lib/api';
import { fmtTokens } from './format';

const ROLE_HINT: Record<string, string> = {
  default: '默认员工可见',
  staff: '员工池可见',
  admin: '管理员可见',
};

export default function PoolsTab() {
  const [pools, setPools] = useState<ModelPool[]>([]);
  const [models, setModels] = useState<AdminModel[]>([]);
  const [providers, setProviders] = useState<string[]>([]);
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [draft, setDraft] = useState<Record<string, boolean>>({});
  const [newName, setNewName] = useState('');
  const [editing, setEditing] = useState<AdminModel | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [{ pools: nextPools }, catalog] = await Promise.all([adminModelPools(), adminModelsCatalog()]);
      setPools(nextPools);
      setModels(catalog.models);
      setProviders(Object.keys(catalog.providers ?? {}));
      setCurrentId((prev) => (prev && nextPools.some((p) => p.id === prev) ? prev : nextPools[0]?.id ?? null));
      setError('');
    } catch (e) {
      setError(`加载失败：${(e as Error).message}`);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const current = pools.find((p) => p.id === currentId) ?? null;
  useEffect(() => {
    if (!current) return;
    setDraft(Object.fromEntries(current.models.map((m) => [m.model_name, m.enabled])));
  }, [current]);

  const savePool = async () => {
    if (!current) return;
    setBusy(true);
    try {
      await adminSavePoolModels(
        current.id,
        Object.entries(draft).map(([model_name, enabled]) => ({ model_name, enabled })),
      );
      setNotice(`已保存「${current.name}」的可见模型`);
      await load();
      setTimeout(() => setNotice(''), 3000);
    } catch (e) {
      setError(`保存失败：${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const createPool = async () => {
    const name = newName.trim();
    if (!name) return;
    setBusy(true);
    try {
      await adminCreatePool(name);
      setNewName('');
      await load();
      setNotice(`已创建池「${name}」`);
      setTimeout(() => setNotice(''), 3000);
    } catch (e) {
      setError(`创建失败：${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const removePool = async (p: ModelPool) => {
    setBusy(true);
    try {
      await adminDeletePool(p.id);
      await load();
      setNotice(`已删除池「${p.name}」`);
      setTimeout(() => setNotice(''), 3000);
    } catch (e) {
      setError(`删除失败：${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const dialogue = useMemo(() => models.filter((m) => m.in_dialogue || m.role == null), [models]);
  const enabledCount = Object.values(draft).filter(Boolean).length;

  return (
    <div className="admin-stack">
      {error && <div className="banner err">{error}</div>}
      {notice && <div className="banner ok">{notice}</div>}
      <p className="admin-sub">按角色池决定谁能看见哪些对话模型；右侧可改名称、描述、参数、渠道和启用。</p>
      <div className="admin-pool-layout">
        <section className="admin-panel">
          <h3>角色 / 可见范围</h3>
          <div className="admin-toolbar">
            <input
              className="admin-search"
              placeholder="新池名（如 finance）"
              value={newName}
              maxLength={32}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') void createPool(); }}
            />
            <button type="button" className="admin-btn" disabled={busy || !newName.trim()} onClick={() => void createPool()}>新建</button>
          </div>
          <div className="admin-role-list">
            {pools.map((p) => (
              <button
                key={p.id}
                type="button"
                className={`admin-role-item ${p.id === currentId ? 'on' : ''}`}
                onClick={() => setCurrentId(p.id)}
              >
                <strong>{p.name}</strong>
                <span>{ROLE_HINT[p.name] ?? `${p.user_count} 人`}</span>
                <em>{p.user_count} 人</em>
              </button>
            ))}
          </div>
          {current && current.user_count === 0 && !ROLE_HINT[current.name] && (
            <button type="button" className="admin-btn ghost" disabled={busy} onClick={() => void removePool(current)}>删除该池</button>
          )}
        </section>

        <section className="admin-panel">
          {!current && <p className="admin-sub">先选择一个角色池。</p>}
          {current && (
            <>
              <div className="admin-section-head">
                <h3>「{current.name}」可见模型（{enabledCount}）</h3>
                <button type="button" className="admin-btn" disabled={busy} onClick={() => void savePool()}>
                  {busy ? '保存中…' : '保存可见性'}
                </button>
              </div>
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>可见</th>
                    <th>名称</th>
                    <th>渠道</th>
                    <th>上下文 / 输出</th>
                    <th>启用</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {dialogue.map((m) => (
                    <tr key={m.id} className={m.enabled === false ? 'dim' : ''}>
                      <td>
                        <input
                          type="checkbox"
                          checked={!!draft[m.id]}
                          onChange={(e) => setDraft((prev) => ({ ...prev, [m.id]: e.target.checked }))}
                        />
                      </td>
                      <td>
                        <strong>{m.name}</strong>
                        <div className="admin-muted">{m.id}</div>
                      </td>
                      <td>{m.provider}</td>
                      <td className="admin-muted">{fmtTokens(m.context_window ?? 0)} / {fmtTokens(m.max_output ?? 0)}</td>
                      <td>{m.enabled === false ? '已关闭' : '启用'}</td>
                      <td><button type="button" className="admin-btn ghost" onClick={() => setEditing(m)}>编辑</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>
      </div>

      {editing && (
        <ModelEditModal
          model={editing}
          providers={providers}
          onClose={() => setEditing(null)}
          onSaved={async (msg) => {
            setNotice(msg);
            setEditing(null);
            await load();
            setTimeout(() => setNotice(''), 3000);
          }}
          onError={setError}
        />
      )}
    </div>
  );
}

function ModelEditModal({
  model,
  providers,
  onClose,
  onSaved,
  onError,
}: {
  model: AdminModel;
  providers: string[];
  onClose: () => void;
  onSaved: (msg: string) => Promise<void>;
  onError: (msg: string) => void;
}) {
  const [name, setName] = useState(model.name);
  const [description, setDescription] = useState(model.description ?? '');
  const [provider, setProvider] = useState(model.provider);
  const [apiModel, setApiModel] = useState(model.api_model ?? '');
  const [context, setContext] = useState(String(model.context_window ?? 0));
  const [maxOut, setMaxOut] = useState(String(model.max_output ?? 0));
  const [cost, setCost] = useState(String(model.cost_per_1k ?? 0));
  const [enabled, setEnabled] = useState(model.enabled !== false);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      await adminUpdateModel(model.id, {
        name: name.trim() || model.name,
        description,
        provider,
        api_model: apiModel,
        context_window: Number(context) || 0,
        max_output: Number(maxOut) || 0,
        cost_per_1k: Number(cost) || 0,
        enabled,
        in_dialogue: model.in_dialogue,
      });
      await onSaved(`已更新 ${name || model.id}`);
    } catch (e) {
      onError(`保存失败：${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ui-confirm-mask" onClick={onClose}>
      <div className="ui-confirm admin-model-edit" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <h3>编辑模型</h3>
        <p className="admin-sub mono">{model.id}</p>
        <label className="admin-field">名称<input value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label className="admin-field">描述<textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} /></label>
        <label className="admin-field">
          渠道
          <Select
            width={220}
            value={provider}
            options={(providers.includes(provider) ? providers : [provider, ...providers]).map((p) => ({ value: p, label: p }))}
            onChange={setProvider}
          />
        </label>
        <label className="admin-field">调用名<input value={apiModel} onChange={(e) => setApiModel(e.target.value)} /></label>
        <div className="admin-field-row">
          <label className="admin-field">上下文窗口<input value={context} onChange={(e) => setContext(e.target.value.replace(/[^\d]/g, ''))} /></label>
          <label className="admin-field">单次最多输出<input value={maxOut} onChange={(e) => setMaxOut(e.target.value.replace(/[^\d]/g, ''))} /></label>
          <label className="admin-field">每千 token 成本<input value={cost} onChange={(e) => setCost(e.target.value)} /></label>
        </div>
        <label className="admin-check">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          启用（关闭后不进对话下拉）
        </label>
        <div className="ui-confirm-actions">
          <button type="button" className="admin-btn ghost" onClick={onClose}>取消</button>
          <button type="button" className="admin-btn" disabled={busy} onClick={() => void save()}>{busy ? '保存中…' : '保存'}</button>
        </div>
      </div>
    </div>
  );
}
