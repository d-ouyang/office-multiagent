import { useCallback, useEffect, useState } from 'react';

import AdminApp from './AdminApp';
import LoginPage from './pages/LoginPage';
import WorkspacePage from './pages/WorkspacePage';
import { checkSession, type LoginUser } from './lib/api';

type View = 'workspace' | 'admin';

/** p6.26 → p6.27：极简路由——/admin（或 #/admin）进管理端应用（自带登录态与登录页）。 */
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

  // 前进/后退（popstate）与手改 hash 都同步视图；管理端点"返回工作台"也走这里
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
  // 管理端优先于工作台登录态：/admin 有自己的登录页与 token，
  // 不依赖（也不消耗）工作台登录态——避免"先登工作台再登管理端"的双重登录。
  if (view === 'admin') {
    return <AdminApp />;
  }
  if (!user) {
    return <LoginPage onLoggedin={setUser} />;
  }
  const isAdmin = user.role === 'admin' || user.role === 'superadmin';
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
