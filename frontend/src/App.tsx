import { useCallback, useEffect, useState } from 'react';

import AdminPage from './pages/AdminPage';
import LoginPage from './pages/LoginPage';
import WorkspacePage from './pages/WorkspacePage';
import { checkSession, type LoginUser } from './lib/api';

type View = 'workspace' | 'admin';

/** p6.26：极简路由——/admin（或 #/admin）进管理端；没有引 react-router。 */
export function readView(): View {
  if (typeof window === 'undefined') return 'workspace';
  const path = window.location.pathname.replace(/\/+$/, '');
  if (path === '/admin' || window.location.hash === '#/admin') return 'admin';
  return 'workspace';
}

export default function App() {
  const [user, setUser] = useState<LoginUser | null>(null);
  const [checking, setChecking] = useState(true);
  const [view, setView] = useState<View>(readView);

  useEffect(() => {
    checkSession().then((u) => {
      setUser(u);
      setChecking(false);
    });
  }, []);

  // 前进/后退（popstate）与手改 hash 都同步视图
  useEffect(() => {
    const sync = () => setView(readView());
    window.addEventListener('popstate', sync);
    window.addEventListener('hashchange', sync);
    return () => {
      window.removeEventListener('popstate', sync);
      window.removeEventListener('hashchange', sync);
    };
  }, []);

  const go = useCallback((next: View) => {
    window.history.pushState({}, '', next === 'admin' ? '/admin' : '/');
    setView(next);
  }, []);

  if (checking) {
    return <div className="page">加载中…</div>;
  }
  if (!user) {
    return <LoginPage onLoggedin={setUser} />;
  }

  const isAdmin = user.role === 'admin' || user.role === 'superadmin';
  // 非管理员直接访问 /admin：回工作台（后端仍会 403，这里只是别让人误以为进去了）
  if (view === 'admin' && !isAdmin) {
    return (
      <WorkspacePage
        user={user}
        onLogout={() => {
          setUser(null);
          window.history.replaceState({}, '', '/');
        }}
      />
    );
  }
  if (view === 'admin') {
    return <AdminPage user={user} onBack={() => go('workspace')} />;
  }
  return (
    <WorkspacePage
      user={user}
      onLogout={() => {
        setUser(null);
        window.history.replaceState({}, '', '/');
      }}
      onOpenAdmin={isAdmin ? () => go('admin') : undefined}
    />
  );
}
