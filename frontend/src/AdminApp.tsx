// 管理端应用（p6.27）：独立登录态 + 侧边菜单 + 个人中心。
// 入口：/admin（或 #/admin）。未登录 → 独立登录页；非管理员 → 登录页直接拒绝。
// 与工作台的关系：两套 token（office_token / office_admin_token），互不影响；
// "返回工作台"只是切视图，不退任何一端登录态。
import { useEffect, useState } from 'react';

import AdminLoginPage from './pages/AdminLoginPage';
import AdminProfilePanel from './components/AdminProfilePanel';
import {
  ADMIN_GROUPS,
  ADMIN_TABS,
  AuditTab,
  ModelPoolsTab,
  OverviewTab,
  RunsTab,
  SystemTab,
  TasksTab,
  UsageTab,
  UsersTab,
  roleLabel,
  type AdminTab,
} from './pages/AdminPanels';
import { adminCheckSession, type LoginUser } from './lib/api';

function readTabFromHash(): AdminTab {
  const key = window.location.hash.replace('#', '') as AdminTab;
  return ADMIN_TABS.some((t) => t.key === key) ? key : 'overview';
}

export default function AdminApp() {
  const [admin, setAdmin] = useState<LoginUser | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    adminCheckSession().then((u) => {
      setAdmin(u);
      setChecking(false);
    });
  }, []);

  if (checking) {
    return <div className="page">加载中…</div>;
  }
  if (!admin) {
    return <AdminLoginPage onLoggedin={setAdmin} />;
  }
  return <AdminShell user={admin} onLogout={() => setAdmin(null)} />;
}

function AdminShell({ user, onLogout }: { user: LoginUser; onLogout: () => void }) {
  const [tab, setTab] = useState<AdminTab>(readTabFromHash);
  const [profileOpen, setProfileOpen] = useState(false);

  // hash 变化（刷新直达 /admin#usage、手改地址栏、前进后退）同步当前面板
  useEffect(() => {
    const sync = () => setTab(readTabFromHash());
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
    <div className="admin-shell">
      <aside className="admin-side">
        <div className="admin-side-brand">
          <span className="admin-login-badge">ADMIN</span>
          <div>
            <strong>管理端</strong>
            <p className="admin-sub">office-multiagent</p>
          </div>
        </div>
        <div className="admin-side-actor">
          <span>当前操作者</span>
          <strong>{user.username}</strong>
          <em>{roleLabel(user.role)}</em>
        </div>
        <nav className="admin-side-nav">
          {ADMIN_GROUPS.map((group) => (
            <div key={group.id} className="admin-side-group">
              <p>{group.label}</p>
              {ADMIN_TABS.filter((t) => t.group === group.id).map((t) => (
                <button
                  key={t.key}
                  type="button"
                  className={`admin-side-item ${tab === t.key ? 'active' : ''}`}
                  onClick={() => select(t.key)}
                >
                  <span className="admin-side-label">{t.label}</span>
                  <span className="admin-side-hint">{t.hint}</span>
                </button>
              ))}
            </div>
          ))}
        </nav>
        <button type="button" className="admin-side-item back" onClick={goWorkspace}>
          <span className="admin-side-label">← 返回工作台</span>
        </button>
        <div className="admin-side-user">
          <button type="button" className="admin-user-chip" onClick={() => setProfileOpen(true)}>
            <span className="account-avatar sm" aria-hidden="true">
              {(user.username || '?').slice(0, 1).toUpperCase()}
            </span>
            <span className="user-info">
              <span className="user-name">{user.username}</span>
              <span className="user-meta">{user.employee_id} · {user.role}</span>
            </span>
          </button>
        </div>
      </aside>

      <main className="admin-main">
        <header className="admin-main-head">
          <div>
            <h2>{active.label}</h2>
            <p className="admin-sub">{active.hint}</p>
          </div>
        </header>
        <div className="admin-main-body">
          {tab === 'overview' && <OverviewTab />}
          {tab === 'users' && <UsersTab />}
          {tab === 'usage' && <UsageTab />}
          {tab === 'tasks' && <TasksTab />}
          {tab === 'runs' && <RunsTab />}
          {tab === 'pools' && <ModelPoolsTab />}
          {tab === 'audit' && <AuditTab />}
          {tab === 'system' && <SystemTab />}
        </div>
      </main>

      {profileOpen && (
        <AdminProfilePanel user={user} onClose={() => setProfileOpen(false)} onLogout={onLogout} />
      )}
    </div>
  );
}

