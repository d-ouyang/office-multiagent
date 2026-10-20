import { useEffect, useState } from 'react';

import LoginPage from './pages/LoginPage';
import WorkspacePage from './pages/WorkspacePage';
import { checkSession, type LoginUser } from './lib/api';

export default function App() {
  const [user, setUser] = useState<LoginUser | null>(null);
  const [checking, setChecking] = useState(true);

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
  return <WorkspacePage user={user} onLogout={() => setUser(null)} />;
}
