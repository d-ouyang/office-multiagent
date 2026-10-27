import {
  AuditOutlined,
  ClusterOutlined,
  DashboardOutlined,
  LikeOutlined,
  LogoutOutlined,
  UnorderedListOutlined,
  UserOutlined,
  WalletOutlined,
} from '@ant-design/icons';
import { useEffect, useState, type ReactNode } from 'react';

import AdminTheme from './admin/theme';
import { Avatar, Button, Layout, Menu, Spin, Typography } from './admin/ui';
import './admin/admin.css';
import AdminLoginPage from './pages/AdminLoginPage';
import AdminProfilePanel from './components/AdminProfilePanel';
import {
  ADMIN_TABS,
  AuditTab,
  FeedbackTab,
  ModelPoolsTab,
  OverviewTab,
  TasksTab,
  UsersTab,
  readAdminTab,
  type AdminTab,
} from './pages/AdminPanels';
import { adminCheckSession, type LoginUser } from './lib/api';

const { Sider, Header, Content } = Layout;

const TAB_ICON: Record<AdminTab, ReactNode> = {
  overview: <DashboardOutlined />,
  tasks: <UnorderedListOutlined />,
  users: <WalletOutlined />,
  pools: <ClusterOutlined />,
  audit: <AuditOutlined />,
  feedback: <LikeOutlined />,
};

export default function AdminApp() {
  const [admin, setAdmin] = useState<LoginUser | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    adminCheckSession().then((u) => {
      setAdmin(u);
      setChecking(false);
    });
  }, []);

  return (
    <AdminTheme>
      {checking ? (
        <div className="admin-boot">
          <Spin size="large" tip="加载中…" />
        </div>
      ) : !admin ? (
        <AdminLoginPage onLoggedin={setAdmin} />
      ) : (
        <AdminShell user={admin} onLogout={() => setAdmin(null)} />
      )}
    </AdminTheme>
  );
}

function AdminShell({ user, onLogout }: { user: LoginUser; onLogout: () => void }) {
  const [tab, setTab] = useState<AdminTab>(readAdminTab);
  const [profileOpen, setProfileOpen] = useState(false);

  useEffect(() => {
    const sync = () => setTab(readAdminTab());
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);

  const select = (key: AdminTab) => {
    setTab(key);
    window.history.replaceState({}, '', `/admin#${key}`);
  };

  const goWorkspace = () => {
    window.history.pushState({}, '', '/');
    window.dispatchEvent(new PopStateEvent('popstate'));
  };

  const active = ADMIN_TABS.find((t) => t.key === tab) ?? ADMIN_TABS[0];

  return (
    <Layout className="admin-antd">
      <Sider width={268} theme="dark" className="admin-antd-sider">
        <div className="admin-side-brand">
          <img className="admin-logo" src="/gq_logo.jpg" alt="锅圈" />
          <div>
            <Typography.Text strong>锅圈Agent Admin</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ margin: 0, fontSize: 13 }}>
              办公助手管理端
            </Typography.Paragraph>
          </div>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[tab]}
          onClick={({ key }) => select(key as AdminTab)}
          items={ADMIN_TABS.map((t) => ({
            key: t.key,
            icon: TAB_ICON[t.key],
            label: t.label,
          }))}
        />
        <div className="admin-sider-foot">
          <Button type="text" icon={<LogoutOutlined />} onClick={goWorkspace} block>
            返回工作台
          </Button>
          <Button type="text" className="admin-user-btn" onClick={() => setProfileOpen(true)} block>
            <Avatar size={28} icon={<UserOutlined />}>
              {(user.username || '?').slice(0, 1).toUpperCase()}
            </Avatar>
            <span className="admin-user-meta">
              <strong>{user.username}</strong>
              <em>账户与退出</em>
            </span>
          </Button>
        </div>
      </Sider>
      <Layout>
        <Header className="admin-antd-header">
          <div>
            <Typography.Title level={3} style={{ margin: 0 }}>{active.label}</Typography.Title>
            <Typography.Text type="secondary">{active.hint}</Typography.Text>
          </div>
        </Header>
        <Content className="admin-antd-content">
          {tab === 'overview' && <OverviewTab />}
          {tab === 'users' && <UsersTab />}
          {tab === 'tasks' && <TasksTab />}
          {tab === 'pools' && <ModelPoolsTab />}
          {tab === 'audit' && <AuditTab />}
          {tab === 'feedback' && <FeedbackTab />}
        </Content>
      </Layout>
      <AdminProfilePanel
        user={user}
        open={profileOpen}
        onClose={() => setProfileOpen(false)}
        onLogout={onLogout}
      />
    </Layout>
  );
}
