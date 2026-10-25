import { useEffect, useState } from 'react';

import AdminLoginPage from './pages/AdminLoginPage';
import AdminProfilePanel from './components/AdminProfilePanel';
import {
  ADMIN_TABS,
  AuditTab,
  ModelPoolsTab,
  OverviewTab,
  TasksTab,
  UsersTab,
  readAdminTab,
  type AdminTab,
} from './pages/AdminPanels';
import { adminCheckSession, type LoginUser } from './lib/api';

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
    <div className="admin-shell">
      <aside className="admin-side">
        <div className="admin-side-brand">
          <img className="admin-logo" src="/gq_logo.jpg" alt="锅圈" />
          <div>
            <strong>锅圈Agent Admin</strong>
            <p className="admin-sub">办公助手管理端</p>
          </div>
        </div>
        <nav className="admin-side-nav">
          {ADMIN_TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              className={`admin-side-item ${tab === t.key ? 'active' : ''}`}
              onClick={() => select(t.key)}
            >
              <span className="admin-side-icon" aria-hidden="true">{t.icon}</span>
              <span className="admin-side-label">{t.label}</span>
            </button>
          ))}
        </nav>
        <button type="button" className="admin-side-item back" onClick={goWorkspace}>
          <span className="admin-side-icon" aria-hidden="true">←</span>
          <span className="admin-side-label">返回工作台</span>
        </button>
        <div className="admin-side-user">
          <button type="button" className="admin-user-chip" onClick={() => setProfileOpen(true)}>
            <span className="account-avatar sm" aria-hidden="true">
              {(user.username || '?').slice(0, 1).toUpperCase()}
            </span>
            <span className="user-info">
              <span className="user-name">{user.username}</span>
              <span className="user-meta">账户与退出</span>
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
          {tab === 'tasks' && <TasksTab />}
          {tab === 'pools' && <ModelPoolsTab />}
          {tab === 'audit' && <AuditTab />}
        </div>
      </main>

      {profileOpen && (
        <AdminProfilePanel user={user} onClose={() => setProfileOpen(false)} onLogout={onLogout} />
      )}
    </div>
  );
}
