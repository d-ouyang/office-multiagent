import { useEffect, useState } from 'react';

import LoginPage from './pages/LoginPage';
import WorkspacePage from './pages/WorkspacePage';
import { checkSession } from './lib/api';

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null); // null=检查中

  useEffect(() => {
    checkSession().then(setAuthed);
  }, []);

  if (authed === null) {
    return <div className="page">加载中…</div>;
  }
  if (!authed) {
    return <LoginPage onLoggedin={() => setAuthed(true)} />;
  }
  return <WorkspacePage onLogout={() => setAuthed(false)} />;
}
