import { useEffect, useState } from 'react';

import AdminPage from './pages/AdminPage';
import LoginPage from './pages/LoginPage';
import WorkspacePage from './pages/WorkspacePage';
import { checkSession, type LoginUser } from './lib/api';

export default function App() {
  const [user, setUser] = useState<LoginUser | null>(null);
  const [checking, setChecking] = useState(true);
  const [view, setView] = useState<'workspace' | 'admin'>('workspace');

  useEffect(() => {
    checkSession().then((u) => {
      setUser(u);
      setChecking(false);
    });
  }, []);

  if (checking) {
    return <div className="page">加载中…</div>;
  }
  if (!user) {
    return <LoginPage onLoggedin={setUser} />;
  }
  // p7.1：管理端独立页面（入口只在 admin/superadmin 侧栏显示；权限由后端强制）
  if (view === 'admin' && (user.role === 'admin' || user.role === 'superadmin')) {
    return <AdminPage user={user} onBack={() => setView('workspace')} />;
  }
  return (
    <WorkspacePage
      user={user}
      onLogout={() => setUser(null)}
      onOpenAdmin={
        user.role === 'admin' || user.role === 'superadmin'
          ? () => setView('admin')
          : undefined
      }
    />
  );
}
