import { useCallback, useEffect, useState } from 'react';

import {
  adminListUsers,
  adminModelPools,
  adminRecharge,
  adminSetUserPool,
  adminUserLedger,
  type AdminUser,
  type LedgerEntry,
  type ModelPool,
} from '../lib/api';
import { AdminListPage, AdminPager, DRAWER_WIDTH, PAGE_SIZE } from './AdminListPage';
import { Ellipsis } from './ellipsis';
import { humanizeAdminError } from './errors';
import { fmtShanghai, fmtTokens, KIND, roleLabel } from './format';
import { Alert, Button, Drawer, Empty, Input, InputNumber, Modal, Select, Space, Table, Tag } from './ui';
import { useDebouncedValue } from './useDebouncedValue';

const ROLE_OPTIONS = [
  { value: '', label: '全部角色' },
  { value: 'user', label: roleLabel('user') },
  { value: 'staff', label: roleLabel('staff') },
  { value: 'admin', label: roleLabel('admin') },
  { value: 'superadmin', label: roleLabel('superadmin') },
];

export default function UsersTab() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pools, setPools] = useState<ModelPool[]>([]);
  const [q, setQ] = useState('');
  const [role, setRole] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [focusId, setFocusId] = useState(() => Number(new URLSearchParams(window.location.search).get('user_id') || 0));
  const [rechargeUser, setRechargeUser] = useState<AdminUser | null>(null);
  const [ledgerUser, setLedgerUser] = useState<AdminUser | null>(null);
  const [loading, setLoading] = useState(false);
  const debouncedQ = useDebouncedValue(q, 300);

  useEffect(() => {
    const sync = () => setFocusId(Number(new URLSearchParams(window.location.search).get('user_id') || 0));
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);

  useEffect(() => {
    setPage(1);
  }, [debouncedQ, role, focusId]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await adminListUsers({
        q: debouncedQ,
        page,
        pageSize: PAGE_SIZE,
        userId: focusId || undefined,
        role: role || undefined,
      });
      setUsers(data.users);
      setTotal(data.total);
      setError('');
    } catch (e) {
      setError(humanizeAdminError(e, '加载用户列表失败，请稍后重试'));
    } finally {
      setLoading(false);
    }
  }, [page, focusId, debouncedQ, role]);

  useEffect(() => {
    void load();
    adminModelPools().then((d) => setPools(d.pools)).catch(() => setPools([]));
  }, [load]);

  const changePool = async (u: AdminUser, poolId: number | null) => {
    try {
      await adminSetUserPool(u.id, poolId);
      setNotice(`已将 ${u.username} 移到 ${poolId ? pools.find((p) => p.id === poolId)?.name ?? poolId : '不限制'}`);
      await load();
      setTimeout(() => setNotice(''), 3000);
    } catch (e) {
      setError(humanizeAdminError(e, '分配失败，请稍后重试'));
    }
  };

  const reset = () => {
    setQ('');
    setRole('');
    setPage(1);
  };

  return (
    <AdminListPage
      filters={(
        <>
          <Input
            allowClear
            placeholder="用户名 / 工号"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            style={{ width: 240 }}
          />
          <Select
            style={{ width: 170 }}
            value={role}
            options={ROLE_OPTIONS}
            onChange={(v) => { setRole(v); setPage(1); }}
          />
          <Button type="link" className="admin-filter-link" onClick={reset}>清空筛选</Button>
          <Button type="link" className="admin-filter-link" onClick={() => void load()}>刷新</Button>
        </>
      )}
      extra={(
        <>
          {error && <Alert type="error" showIcon message={error} />}
          {notice && <Alert type="success" showIcon message={notice} style={{ marginTop: error ? 8 : 0 }} />}
        </>
      )}
      footer={<AdminPager total={total} page={page} onChange={setPage} unit="人" />}
    >
      <Table<AdminUser>
        rowKey="id"
        loading={loading}
        dataSource={users}
        pagination={false}
        tableLayout="fixed"
        rowClassName={(u) => (u.id === focusId ? 'admin-row-active' : '')}
        onRow={(u) => ({
          onClick: (e) => {
            const target = e.target as HTMLElement;
            if (target.closest('button, .ant-select, .ant-switch, a, input')) return;
            setLedgerUser(u);
          },
        })}
        locale={{ emptyText: <Empty description="没有匹配的用户" /> }}
        columns={[
          {
            title: '工号',
            dataIndex: 'employee_id',
            width: 140,
            ellipsis: { showTitle: false },
            render: (v) => <Ellipsis>{v}</Ellipsis>,
          },
          {
            title: '用户名',
            dataIndex: 'username',
            width: 160,
            ellipsis: { showTitle: false },
            render: (v) => <Ellipsis>{v}</Ellipsis>,
          },
          {
            title: '角色',
            dataIndex: 'role',
            width: 140,
            render: (r: string) => (
              <Tag color={r === 'admin' || r === 'superadmin' ? 'blue' : 'default'}>{roleLabel(r)}</Tag>
            ),
          },
          {
            title: '池',
            dataIndex: 'model_pool_id',
            render: (id: number | null | undefined, u) => (
              <Select
                style={{ width: '100%' }}
                value={id ? String(id) : ''}
                onChange={(v) => void changePool(u, v ? Number(v) : null)}
                options={[
                  { value: '', label: '不限制' },
                  ...pools.map((p) => ({ value: String(p.id), label: `${p.name}（${p.user_count} 人）` })),
                ]}
              />
            ),
          },
          {
            title: '余额（token）',
            dataIndex: 'balance',
            width: 150,
            align: 'right',
            render: (n: number) => n.toLocaleString(),
          },
          {
            title: '总使用量',
            dataIndex: 'total_used',
            width: 130,
            align: 'right',
            render: (n?: number) => fmtTokens(n ?? 0),
          },
          {
            title: '操作',
            width: 168,
            render: (_, u) => (
              <Space>
                <Button size="small" type="primary" onClick={() => setRechargeUser(u)}>充值</Button>
                <Button size="small" onClick={() => setLedgerUser(u)}>流水</Button>
              </Space>
            ),
          },
        ]}
      />
      <RechargeModal
        user={rechargeUser}
        onClose={() => setRechargeUser(null)}
        onDone={async (msg) => {
          setNotice(msg);
          setRechargeUser(null);
          await load();
          setTimeout(() => setNotice(''), 4000);
        }}
        onError={setError}
      />
      <LedgerDrawer user={ledgerUser} onClose={() => setLedgerUser(null)} />
    </AdminListPage>
  );
}

function RechargeModal({
  user,
  onClose,
  onDone,
  onError,
}: {
  user: AdminUser | null;
  onClose: () => void;
  onDone: (msg: string) => Promise<void>;
  onError: (msg: string) => void;
}) {
  const [amount, setAmount] = useState<number | null>(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!user) return;
    const value = Number(amount);
    if (!Number.isFinite(value) || value <= 0 || !Number.isInteger(value)) {
      onError('充值数量必须是正整数');
      return;
    }
    setBusy(true);
    try {
      const next = await adminRecharge(user.id, value, note);
      await onDone(`已为 ${user.username} 充值 ${value.toLocaleString()}，当前余额 ${next.toLocaleString()}`);
      setAmount(null);
      setNote('');
    } catch (e) {
      onError(humanizeAdminError(e, '充值失败，请稍后重试'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={!!user}
      title={user ? `给 ${user.username} 充值` : '充值'}
      rootClassName="admin-dialog"
      onCancel={onClose}
      onOk={() => void submit()}
      confirmLoading={busy}
      okText={busy ? '充值中…' : '确认充值'}
      destroyOnHidden
    >
      {user && (
        <Space direction="vertical" style={{ width: '100%' }} size={20}>
          <span>工号 {user.employee_id} · 当前余额 {user.balance.toLocaleString()}</span>
          <InputNumber
            style={{ width: '100%' }}
            min={1}
            placeholder="如 50000"
            value={amount}
            onChange={(v) => setAmount(typeof v === 'number' ? v : null)}
          />
          <Input placeholder="备注（可选）" value={note} onChange={(e) => setNote(e.target.value)} />
        </Space>
      )}
    </Modal>
  );
}

function LedgerDrawer({ user, onClose }: { user: AdminUser | null; onClose: () => void }) {
  const [rows, setRows] = useState<LedgerEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);

  useEffect(() => {
    setPage(1);
  }, [user?.id]);

  useEffect(() => {
    if (!user) return;
    adminUserLedger(user.id, page, PAGE_SIZE).then((data) => {
      setRows(data.ledger);
      setTotal(data.total);
    }).catch(() => {
      setRows([]);
      setTotal(0);
    });
  }, [user, page]);

  const showReserve = rows.some((row) => row.kind === 'reserve' || (row.reserve && !row.settle && !row.amount));

  return (
    <Drawer
      open={!!user}
      title={user ? `${user.username} 的流水` : '流水'}
      width={DRAWER_WIDTH}
      rootClassName="admin-dialog"
      onClose={onClose}
      destroyOnHidden
    >
      {user && (
        <p className="admin-muted" style={{ marginTop: 0 }}>工号 {user.employee_id}</p>
      )}
      <div className="admin-drawer-list">
        <div className="admin-list-body">
          <Table<LedgerEntry>
            rowKey={(row, i) => `${row.task_id ?? i}-${row.created_at ?? i}`}
            dataSource={rows}
            pagination={false}
            tableLayout="fixed"
            locale={{ emptyText: <Empty description="暂无记录" /> }}
            columns={[
              { title: '类型', dataIndex: 'kind', width: 96, render: (k?: string) => KIND[k ?? 'settle'] ?? k },
              { title: '充值数量', width: 120, render: (_, row) => (row.kind === 'recharge' ? (row.amount ?? '—') : '—') },
              { title: '消耗数量', dataIndex: 'settle', width: 120, render: (v) => v ?? '—' },
              ...(showReserve ? [{ title: '预扣', dataIndex: 'reserve' as const, width: 100, render: (v: number | null) => v ?? '—' }] : []),
              {
                title: '备注',
                dataIndex: 'note',
                ellipsis: { showTitle: false },
                render: (v?: string | null) => <Ellipsis>{v ?? '—'}</Ellipsis>,
              },
              {
                title: '时间',
                dataIndex: 'created_at',
                width: 188,
                ellipsis: { showTitle: false },
                render: (v?: string) => <Ellipsis>{fmtShanghai(v)}</Ellipsis>,
              },
            ]}
          />
        </div>
        <div className="admin-list-pager">
          <AdminPager total={total} page={page} onChange={setPage} />
        </div>
      </div>
    </Drawer>
  );
}
