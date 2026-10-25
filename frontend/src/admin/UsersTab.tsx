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
import { humanizeAdminError } from './errors';
import { fmtShanghai, fmtTokens, KIND, roleLabel } from './format';
import { goAdmin } from './nav';
import { Alert, Button, Drawer, Empty, Input, InputNumber, Modal, Select, Space, Table, Tag } from './ui';
import { useDebouncedValue } from './useDebouncedValue';

export default function UsersTab() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pools, setPools] = useState<ModelPool[]>([]);
  const [q, setQ] = useState('');
  const [balance, setBalance] = useState<number | null>(null);
  const [balanceOp, setBalanceOp] = useState<'gt' | 'lt'>('gt');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [focusId, setFocusId] = useState(() => Number(new URLSearchParams(window.location.search).get('user_id') || 0));
  const [rechargeUser, setRechargeUser] = useState<AdminUser | null>(null);
  const [ledgerUser, setLedgerUser] = useState<AdminUser | null>(null);
  const [loading, setLoading] = useState(false);
  const debouncedQ = useDebouncedValue(q, 300);
  const debouncedBalance = useDebouncedValue(balance, 300);

  useEffect(() => {
    const sync = () => setFocusId(Number(new URLSearchParams(window.location.search).get('user_id') || 0));
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);

  useEffect(() => {
    setPage(1);
  }, [debouncedQ, debouncedBalance, balanceOp, focusId]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await adminListUsers({
        q: debouncedQ,
        page,
        pageSize: PAGE_SIZE,
        userId: focusId || undefined,
        balance: debouncedBalance ?? undefined,
        balanceOp: debouncedBalance != null ? balanceOp : undefined,
      });
      setUsers(data.users);
      setTotal(data.total);
      setError('');
    } catch (e) {
      setError(humanizeAdminError(e, '加载用户列表失败，请稍后重试'));
    } finally {
      setLoading(false);
    }
  }, [page, focusId, debouncedQ, debouncedBalance, balanceOp]);

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
    setBalance(null);
    setBalanceOp('gt');
    setPage(1);
  };

  return (
    <AdminListPage
      filters={(
        <>
          <Input
            allowClear
            placeholder="搜索用户名或工号"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            style={{ width: 240 }}
          />
          <InputNumber
            placeholder="余额"
            value={balance}
            onChange={(v) => setBalance(typeof v === 'number' ? v : null)}
            style={{ width: 140 }}
          />
          <Select
            value={balanceOp}
            onChange={setBalanceOp}
            style={{ width: 150 }}
            options={[
              { value: 'gt', label: '大于该数值' },
              { value: 'lt', label: '小于该数值' },
            ]}
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
        tableLayout="auto"
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
          { title: '工号', dataIndex: 'employee_id' },
          { title: '用户名', dataIndex: 'username' },
          {
            title: '角色',
            dataIndex: 'role',
            render: (role: string) => (
              <Tag color={role === 'admin' || role === 'superadmin' ? 'blue' : 'default'}>{roleLabel(role)}</Tag>
            ),
          },
          {
            title: '池',
            dataIndex: 'model_pool_id',
            render: (id: number | null | undefined, u) => (
              <Select
                style={{ minWidth: 160 }}
                value={id ? String(id) : ''}
                onChange={(v) => void changePool(u, v ? Number(v) : null)}
                options={[
                  { value: '', label: '不限制' },
                  ...pools.map((p) => ({ value: String(p.id), label: `${p.name}（${p.user_count} 人）` })),
                ]}
              />
            ),
          },
          { title: '余额（token）', dataIndex: 'balance', align: 'right', render: (n: number) => n.toLocaleString() },
          { title: '总使用量', dataIndex: 'total_used', align: 'right', render: (n?: number) => fmtTokens(n ?? 0) },
          {
            title: '操作',
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
      onCancel={onClose}
      onOk={() => void submit()}
      confirmLoading={busy}
      okText={busy ? '充值中…' : '确认充值'}
      destroyOnHidden
    >
      {user && (
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
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

  const openTask = (taskId: string) => {
    onClose();
    goAdmin('tasks', { task_id: taskId, open: '1' });
  };

  return (
    <Drawer
      open={!!user}
      title={user ? `${user.username} 的流水` : '流水'}
      width={DRAWER_WIDTH}
      onClose={onClose}
      destroyOnHidden
    >
      {user && (
        <p className="admin-muted" style={{ marginTop: 0 }}>工号 {user.employee_id} · 点「详情」跳到任务监控并打开该任务</p>
      )}
      <div className="admin-drawer-list">
        <div className="admin-list-body">
          <Table<LedgerEntry>
            rowKey={(row, i) => `${row.task_id ?? i}-${row.created_at ?? i}`}
            dataSource={rows}
            pagination={false}
            tableLayout="auto"
            locale={{ emptyText: <Empty description="暂无记录" /> }}
            columns={[
              { title: '类型', dataIndex: 'kind', render: (k?: string) => KIND[k ?? 'settle'] ?? k },
              { title: '充值数量', render: (_, row) => (row.kind === 'recharge' ? (row.amount ?? '—') : '—') },
              { title: '消耗数量', dataIndex: 'settle', render: (v) => v ?? '—' },
              ...(showReserve ? [{ title: '预扣', dataIndex: 'reserve' as const, render: (v: number | null) => v ?? '—' }] : []),
              { title: '备注', dataIndex: 'note', render: (v?: string | null) => v ?? '—' },
              { title: '时间', dataIndex: 'created_at', render: (v?: string) => fmtShanghai(v) },
              {
                title: '',
                render: (_, row) => row.task_id ? (
                  <Button type="link" onClick={() => openTask(String(row.task_id))}>详情</Button>
                ) : '—',
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
