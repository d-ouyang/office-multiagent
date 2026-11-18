// 登录页交互：密码明文切换 + 登录成功后交给浏览器保存凭据。
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { login } from '../lib/api';
import LoginPage from './LoginPage';

vi.mock('../lib/api', () => ({ login: vi.fn() }));

const loginMock = vi.mocked(login);

class FakePasswordCredential {
  constructor(public data: { id: string; password: string; name?: string }) {}
}

let store: ReturnType<typeof vi.fn>;

beforeEach(() => {
  store = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal('PasswordCredential', FakePasswordCredential);
  vi.stubGlobal('requestAnimationFrame', (cb: () => void) => { cb(); return 0; });
  Object.defineProperty(navigator, 'credentials', {
    configurable: true,
    value: { store },
  });
  loginMock.mockReset();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  Object.defineProperty(navigator, 'credentials', { configurable: true, value: undefined });
});

function fillForm(password = 'Office@2026') {
  fireEvent.change(screen.getByPlaceholderText('登录名'), { target: { value: 'dev' } });
  fireEvent.change(screen.getByPlaceholderText('密码'), { target: { value: password } });
}

describe('LoginPage · 密码明文切换', () => {
  it('默认密文；点眼睛变明文并更新无障碍状态，再点回到密文', () => {
    render(<LoginPage onLoggedin={vi.fn()} />);
    const input = screen.getByPlaceholderText('密码') as HTMLInputElement;

    expect(input.type).toBe('password');
    expect(screen.getByRole('button', { name: '显示密码' })).toHaveAttribute('aria-pressed', 'false');

    fireEvent.click(screen.getByRole('button', { name: '显示密码' }));
    expect(input.type).toBe('text');
    expect(screen.getByRole('button', { name: '隐藏密码' })).toHaveAttribute('aria-pressed', 'true');
    // 眼睛是 type=button，不能顺带提交表单
    expect(loginMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: '隐藏密码' }));
    expect(input.type).toBe('password');
  });

  it('切换明文不丢失已输入内容，且 name / autocomplete 保持稳定', () => {
    render(<LoginPage onLoggedin={vi.fn()} />);
    const input = screen.getByPlaceholderText('密码') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'abc123' } });
    fireEvent.click(screen.getByRole('button', { name: '显示密码' }));

    expect(input.value).toBe('abc123');
    expect(input).toHaveAttribute('name', 'password');
    expect(input).toHaveAttribute('autocomplete', 'current-password');
  });
});

describe('LoginPage · 浏览器保存凭据', () => {
  it('登录成功后保存显式凭据对象（id / password 齐全）', async () => {
    loginMock.mockResolvedValue({} as never);
    const onLoggedin = vi.fn();
    render(<LoginPage onLoggedin={onLoggedin} />);

    fillForm();
    fireEvent.click(screen.getByRole('button', { name: /登\s*录/ }));

    await waitFor(() => expect(store).toHaveBeenCalledTimes(1));
    const cred = store.mock.calls[0][0] as FakePasswordCredential;
    expect(cred).toBeInstanceOf(FakePasswordCredential);
    expect(cred.data).toEqual({ id: 'dev', password: 'Office@2026', name: 'dev' });
    expect(onLoggedin).toHaveBeenCalledTimes(1);
  });

  it('开着「显示密码」提交时仍能保存（凭据不依赖 type=password 的表单解析）', async () => {
    loginMock.mockResolvedValue({} as never);
    render(<LoginPage onLoggedin={vi.fn()} />);

    fillForm('PlainText@2026');
    fireEvent.click(screen.getByRole('button', { name: '显示密码' }));
    expect((screen.getByPlaceholderText('密码') as HTMLInputElement).type).toBe('text');
    fireEvent.click(screen.getByRole('button', { name: /登\s*录/ }));

    await waitFor(() => expect(store).toHaveBeenCalledTimes(1));
    expect((store.mock.calls[0][0] as FakePasswordCredential).data.password).toBe('PlainText@2026');
  });

  it('登录失败不保存凭据，避免把错误密码写进密码管理器', async () => {
    loginMock.mockRejectedValue(new Error('账号或密码错误'));
    const onLoggedin = vi.fn();
    render(<LoginPage onLoggedin={onLoggedin} />);

    fillForm('wrong');
    fireEvent.click(screen.getByRole('button', { name: /登\s*录/ }));

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('账号或密码错误'));
    expect(store).not.toHaveBeenCalled();
    expect(onLoggedin).not.toHaveBeenCalled();
  });
});
