import { useCallback, useEffect, useMemo, useState } from 'react';

import { AdminListPage, DRAWER_WIDTH } from './AdminListPage';

import {
  adminCreateModel,
  adminCreatePool,
  adminDeletePool,
  adminModelPools,
  adminModelsCatalog,
  adminSavePoolModels,
  adminUpdateModel,
  type AdminModel,
  type ModelPool,
} from '../lib/api';
import { Ellipsis } from './ellipsis';
import { humanizeAdminError } from './errors';
import { fmtTokens } from './format';
import { Alert, Button, Drawer, Empty, Form, Input, InputNumber, Modal, Select, Space, Switch, Table, Typography } from './ui';

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
  const [poolOpen, setPoolOpen] = useState(false);
  const [editing, setEditing] = useState<AdminModel | null>(null);
  const [creating, setCreating] = useState(false);
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
      setError(humanizeAdminError(e, '加载模型池失败，请稍后重试'));
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
      const closed = new Set(models.filter((m) => m.enabled === false).map((m) => m.id));
      await adminSavePoolModels(
        current.id,
        Object.entries(draft).map(([model_name, enabled]) => ({
          model_name,
          enabled: closed.has(model_name) ? false : enabled,
        })),
      );
      setNotice(`已保存「${current.name}」的可见模型`);
      await load();
      setTimeout(() => setNotice(''), 3000);
    } catch (e) {
      setError(humanizeAdminError(e, '保存失败，请稍后重试'));
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
      setPoolOpen(false);
      await load();
      setNotice(`已创建池「${name}」`);
      setTimeout(() => setNotice(''), 3000);
    } catch (e) {
      setError(humanizeAdminError(e, '创建失败，请稍后重试'));
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
      setError(humanizeAdminError(e, '删除失败，请稍后重试'));
    } finally {
      setBusy(false);
    }
  };

  const toggleEnabled = async (m: AdminModel, enabled: boolean) => {
    try {
      await adminUpdateModel(m.id, { enabled, in_dialogue: m.in_dialogue });
      if (!enabled) setDraft((prev) => ({ ...prev, [m.id]: false }));
      setNotice(enabled ? `已启用 ${m.name}` : `已关闭 ${m.name}（不再出现在模型池）`);
      await load();
      setTimeout(() => setNotice(''), 3000);
    } catch (e) {
      setError(humanizeAdminError(e, '更新启用状态失败，请稍后重试'));
    }
  };

  const dialogue = useMemo(
    () => models.filter((m) => (m.in_dialogue || m.role == null) && m.enabled !== false),
    [models],
  );
  const enabledCount = dialogue.filter((m) => draft[m.id]).length;

  return (
    <AdminListPage
      filters={(
        <>
          <Select
            style={{ minWidth: 260 }}
            value={currentId ?? undefined}
            placeholder="角色 / 可见范围"
            onChange={(id) => setCurrentId(id)}
            options={pools.map((p) => ({
              value: p.id,
              label: `${p.name} · ${ROLE_HINT[p.name] ?? `${p.user_count} 人`}`,
            }))}
          />
          <Button type="primary" disabled={busy || !current} onClick={() => void savePool()}>
            {busy ? '保存中…' : '保存可见性'}
          </Button>
          <Button type="primary" onClick={() => { setNewName(''); setPoolOpen(true); }}>新建池</Button>
          {current && current.user_count === 0 && !ROLE_HINT[current.name] && (
            <Button danger disabled={busy} onClick={() => void removePool(current)}>删除该池</Button>
          )}
          <Button onClick={() => setCreating(true)}>新建模型</Button>
          <Button type="link" className="admin-filter-link" onClick={() => void load()}>刷新</Button>
        </>
      )}
      extra={(
        <>
          {error && <Alert type="error" showIcon message={error} />}
          {notice && <Alert type="success" showIcon message={notice} style={{ marginTop: error ? 8 : 0 }} />}
        </>
      )}
    >
      {!current && <Empty description="先选择一个角色池。" />}
      {current && (
        <Table<AdminModel>
          rowKey="id"
          dataSource={dialogue}
          pagination={false}
          tableLayout="fixed"
          locale={{ emptyText: <Empty description="没有已开启的模型" /> }}
          title={() => `「${current.name}」可见模型（${enabledCount}）`}
          columns={[
            {
              title: '可见',
              width: 88,
              render: (_, m) => (
                <Switch
                  checked={!!draft[m.id]}
                  onChange={(checked) => setDraft((prev) => ({ ...prev, [m.id]: checked }))}
                />
              ),
            },
            {
              title: '名称',
              ellipsis: true,
              render: (_, m) => m.name,
            },
            {
              title: '模型id',
              dataIndex: 'id',
              width: 240,
              ellipsis: true,
            },
            {
              title: '实际调用名',
              dataIndex: 'api_model',
              width: 360,
              ellipsis: { showTitle: false },
              render: (v?: string) => <Ellipsis title={v || '—'}>{v || '—'}</Ellipsis>,
            },
            {
              title: '渠道',
              dataIndex: 'provider',
              width: 132,
              ellipsis: { showTitle: false },
              render: (v?: string) => <Ellipsis>{v || '—'}</Ellipsis>,
            },
            {
              title: '上下文 / 输出',
              width: 176,
              render: (_, m) => `${fmtTokens(m.context_window ?? 0)} / ${fmtTokens(m.max_output ?? 0)}`,
            },
            {
              title: '启用',
              width: 108,
              render: (_, m) => (
                <Switch
                  checked={m.enabled !== false}
                  checkedChildren="开启"
                  unCheckedChildren="关闭"
                  onChange={(checked) => void toggleEnabled(m, checked)}
                />
              ),
            },
            {
              title: '操作',
              width: 96,
              render: (_, m) => <Button onClick={() => setEditing(m)}>编辑</Button>,
            },
          ]}
        />
      )}

      <Modal
        open={poolOpen}
        title="新建模型池"
        rootClassName="admin-dialog"
        onCancel={() => setPoolOpen(false)}
        onOk={() => void createPool()}
        okButtonProps={{ disabled: busy || !newName.trim() }}
        confirmLoading={busy}
        okText={busy ? '创建中…' : '创建'}
        destroyOnHidden
      >
        <Form layout="vertical" requiredMark={false}>
          <Form.Item label="池名" extra="例如 finance，用来按角色或部门划分可见模型。">
            <Input
              placeholder="如 finance"
              value={newName}
              maxLength={32}
              autoFocus
              onChange={(e) => setNewName(e.target.value)}
              onPressEnter={() => void createPool()}
            />
          </Form.Item>
        </Form>
      </Modal>
      <ModelFormDrawer
        open={!!editing || creating}
        model={editing}
        creating={creating}
        providers={providers}
        onClose={() => { setEditing(null); setCreating(false); }}
        onSaved={async (msg) => {
          setNotice(msg);
          setEditing(null);
          setCreating(false);
          await load();
          setTimeout(() => setNotice(''), 3000);
        }}
        onError={setError}
      />
    </AdminListPage>
  );
}

function ModelFormDrawer({
  open,
  model,
  creating,
  providers,
  onClose,
  onSaved,
  onError,
}: {
  open: boolean;
  model: AdminModel | null;
  creating: boolean;
  providers: string[];
  onClose: () => void;
  onSaved: (msg: string) => Promise<void>;
  onError: (msg: string) => void;
}) {
  const [form] = Form.useForm();
  const [busy, setBusy] = useState(false);
  const providerOptions = useMemo(() => {
    const current = model?.provider;
    const list = current && !providers.includes(current) ? [current, ...providers] : providers;
    return list.map((p) => ({ value: p, label: p }));
  }, [providers, model]);

  useEffect(() => {
    if (!open) return;
    if (creating) {
      form.setFieldsValue({
        id: '',
        name: '',
        description: '',
        provider: providers[0],
        api_model: '',
        context_window: 0,
        max_output: 0,
        cost_per_1k: 0,
        enabled: true,
      });
      return;
    }
    if (model) {
      form.setFieldsValue({
        id: model.id,
        name: model.name,
        description: model.description ?? '',
        provider: model.provider,
        api_model: model.api_model ?? '',
        context_window: model.context_window ?? 0,
        max_output: model.max_output ?? 0,
        cost_per_1k: model.cost_per_1k ?? 0,
        enabled: model.enabled !== false,
      });
    }
  }, [open, creating, model, providers, form]);

  const save = async () => {
    let values: {
      id: string;
      name: string;
      description?: string;
      provider: string;
      api_model: string;
      context_window?: number;
      max_output?: number;
      cost_per_1k?: number;
      enabled?: boolean;
    };
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setBusy(true);
    try {
      if (creating) {
        await adminCreateModel({
          id: String(values.id).trim(),
          name: String(values.name).trim(),
          description: values.description,
          provider: values.provider,
          api_model: String(values.api_model).trim(),
          context_window: Number(values.context_window) || 0,
          max_output: Number(values.max_output) || 0,
          cost_per_1k: Number(values.cost_per_1k) || 0,
          enabled: !!values.enabled,
          in_dialogue: true,
        });
        await onSaved(`已新建 ${values.name || values.id}`);
      } else if (model) {
        await adminUpdateModel(model.id, {
          name: String(values.name).trim() || model.name,
          description: values.description,
          provider: values.provider,
          api_model: String(values.api_model).trim(),
          context_window: Number(values.context_window) || 0,
          max_output: Number(values.max_output) || 0,
          cost_per_1k: Number(values.cost_per_1k) || 0,
          enabled: !!values.enabled,
          in_dialogue: model.in_dialogue,
        });
        await onSaved(`已更新 ${values.name || model.id}`);
      }
    } catch (e) {
      onError(humanizeAdminError(e, '保存失败，请稍后重试'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Drawer
      open={open}
      title={creating ? '新建模型' : '编辑模型'}
      width={DRAWER_WIDTH}
      rootClassName="admin-dialog"
      onClose={onClose}
      destroyOnHidden
      footer={(
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={busy} onClick={() => void save()}>
            {busy ? '保存中…' : '保存'}
          </Button>
        </Space>
      )}
    >
      <Form form={form} layout="vertical" requiredMark={false} className="admin-dialog-form">
        <Form.Item
          name="id"
          label="登记 id"
          extra="内部稳定键，例如 deepseek-v4.1-flash-sf。创建后不可改。"
          rules={creating ? [{ required: true, message: '请填写登记 id' }] : undefined}
        >
          <Input disabled={!creating} placeholder="deepseek-v4.1-flash-sf" />
        </Form.Item>
        <Form.Item name="name" label="名称" rules={[{ required: true, message: '请填写名称' }]}>
          <Input />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea rows={3} />
        </Form.Item>
        <Form.Item name="provider" label="渠道" rules={[{ required: true, message: '请选择渠道' }]}>
          <Select options={providerOptions} />
        </Form.Item>
        <Form.Item
          name="api_model"
          label="实际调用名"
          extra="发给供应商 /chat/completions 的 model 字段，例如 deepseek-ai/DeepSeek-V4.1-Flash，不是登记 id 或 *-sf 短名。"
          rules={[{ required: true, message: '请填写实际调用名' }]}
        >
          <Input placeholder="deepseek-ai/DeepSeek-V4.1-Flash" />
        </Form.Item>
        <Space size={12} style={{ width: '100%' }} className="admin-model-nums">
          <Form.Item name="context_window" label="上下文窗口">
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="max_output" label="单次最多输出">
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="cost_per_1k" label="每千 token 成本">
            <InputNumber min={0} step={0.0001} style={{ width: '100%' }} />
          </Form.Item>
        </Space>
        <Form.Item name="enabled" label="启用" valuePropName="checked">
          <Switch checkedChildren="开启" unCheckedChildren="关闭" />
        </Form.Item>
        <Typography.Paragraph type="secondary">
          关闭后不会出现在模型池，也不会进入对话下拉。模型 id 给系统内部用；实际调用名才是渠道接口收到的名字。
        </Typography.Paragraph>
      </Form>
    </Drawer>
  );
}
