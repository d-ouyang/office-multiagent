import { lazy, Suspense, useCallback, useEffect, useState } from 'react';

// v2.2.0-p1.13（F1）：路由级代码分割——AdminApp（管理端含图表重依赖）与
// WorkspacePage 拆为独立 chunk，首屏只加载当前视图的包。
const AdminApp = lazy(() => import('./AdminApp'));
const LoginPage = lazy(() => import('./pages/LoginPage'));
const WorkspacePage = lazy(() => import('./pages/WorkspacePage'));
import { checkSession, clearToken, type LoginUser } from './lib/api';

function RouteFallback() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', padding: 48, color: '#888' }}>
      加载中…
    </div>
  );
}

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
    return (
      <Suspense fallback={<RouteFallback />}>
        <AdminApp />
      </Suspense>
    );
  }
  if (!user) {
    return (
      <Suspense fallback={<RouteFallback />}>
        <LoginPage onLoggedin={setUser} />
      </Suspense>
    );
  }
  const isAdmin = user.role === 'admin' || user.role === 'superadmin';
  return (
    <Suspense fallback={<RouteFallback />}>
    <WorkspacePage
      user={user}
      onLogout={() => {
        // 退出必须清掉本地 token：否则刷新后 checkSession() 会拿残留 token 静默自动登录。
        clearToken();
        setUser(null);
        window.history.replaceState({}, '', '/');
      }}
      onOpenAdmin={isAdmin ? () => go('admin') : undefined}
    />
    </Suspense>
  );
}
