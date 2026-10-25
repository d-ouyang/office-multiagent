import { Button, Card, Form, Input, Typography } from 'antd';
import { useState } from 'react';

import { humanizeAdminError } from '../admin/errors';
import { adminLogin, type LoginUser } from '../lib/api';

function goWorkspace() {
  window.history.pushState({}, '', '/');
  window.dispatchEvent(new PopStateEvent('popstate'));
}

export default function AdminLoginPage({ onLoggedin }: { onLoggedin: (u: LoginUser) => void }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (values: { username: string; password: string }) => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      onLoggedin(await adminLogin(values.username.trim(), values.password));
    } catch (err) {
      setError(humanizeAdminError(err, '登录失败，请检查账号或稍后重试'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="admin-login-page">
      <Card className="admin-login-card">
        <div className="admin-login-brand">
          <img className="admin-logo" src="/gq_logo.jpg" alt="锅圈" />
          <Typography.Title level={3} style={{ margin: 0 }}>锅圈Agent Admin</Typography.Title>
        </div>
        <Typography.Paragraph type="secondary">仅管理员账号可登录</Typography.Paragraph>
        <Form layout="vertical" onFinish={submit} requiredMark={false}>
          <Form.Item name="username" rules={[{ required: true, message: '请输入管理员账号' }]}>
            <Input name="username" placeholder="管理员账号" autoFocus autoComplete="username" size="large" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password name="password" placeholder="密码" autoComplete="current-password" size="large" />
          </Form.Item>
          {error && <Typography.Paragraph type="danger" role="alert">{error}</Typography.Paragraph>}
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={busy} block size="large">
              {busy ? '登录中…' : '登录管理端'}
            </Button>
          </Form.Item>
        </Form>
        <Button type="link" onClick={goWorkspace} block>← 返回工作台</Button>
      </Card>
    </div>
  );
}
