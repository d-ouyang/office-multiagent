import { useState } from 'react';

import { humanizeAdminError } from '../admin/errors';
import { Alert, Button, Form, Input, Modal, Space, Typography } from '../admin/ui';
import { adminChangePassword, adminClearToken, adminLogout, type LoginUser } from '../lib/api';

export default function AdminProfilePanel({
  user,
  open,
  onClose,
  onLogout,
}: {
  user: LoginUser;
  open: boolean;
  onClose: () => void;
  onLogout: () => void;
}) {
  const [form] = Form.useForm();
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (values: { oldPassword: string; newPassword: string; confirm: string }) => {
    setError('');
    setNotice('');
    if (values.newPassword.length < 6) {
      setError('新密码至少 6 位');
      return;
    }
    if (values.newPassword !== values.confirm) {
      setError('两次输入的新密码不一致');
      return;
    }
    setBusy(true);
    try {
      await adminChangePassword(values.oldPassword, values.newPassword);
      setNotice('密码已修改，管理端登录态已自动更新');
      form.resetFields();
    } catch (err) {
      setError(humanizeAdminError(err, '修改失败，请稍后重试'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      title="账户与退出"
      rootClassName="admin-dialog"
      onCancel={onClose}
      footer={null}
      destroyOnHidden
    >
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <div>
          <Typography.Text strong>{user.username}</Typography.Text>
          <Typography.Paragraph type="secondary" style={{ margin: '4px 0 0' }}>
            {user.employee_id} · {user.role}
          </Typography.Paragraph>
        </div>
        {notice && <Alert type="success" showIcon message={notice} />}
        {error && <Alert type="error" showIcon message={error} />}
        <Form form={form} layout="vertical" onFinish={submit} requiredMark={false}>
          <Typography.Title level={5}>修改密码</Typography.Title>
          <Form.Item name="oldPassword" rules={[{ required: true, message: '请输入当前密码' }]}>
            <Input.Password placeholder="当前密码" autoComplete="current-password" />
          </Form.Item>
          <Form.Item name="newPassword" rules={[{ required: true, message: '请输入新密码' }]}>
            <Input.Password placeholder="新密码（至少 6 位）" autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="confirm" rules={[{ required: true, message: '请再次输入新密码' }]}>
            <Input.Password placeholder="确认新密码" autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={busy} block>
            {busy ? '提交中…' : '修改密码'}
          </Button>
          <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
            修改成功后旧密码立即失效；管理端登录态会自动换成新 token。
          </Typography.Paragraph>
        </Form>
        <Button
          danger
          onClick={() => {
            void adminLogout().finally(() => {
              adminClearToken();
              onLogout();
            });
          }}
        >
          退出管理端
        </Button>
      </Space>
    </Modal>
  );
}
