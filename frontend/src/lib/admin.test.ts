// p6.26：管理端路由与用量格式化（纯函数，jsdom 环境）
import { readView } from '../App';
import { fmtTokens } from '../pages/AdminPage';

describe('readView（管理端独立路由）', () => {
  afterEach(() => {
    window.history.replaceState({}, '', '/');
  });

  it('/admin 进管理端', () => {
    window.history.pushState({}, '', '/admin');
    expect(readView()).toBe('admin');
  });

  it('尾斜杠 /admin/ 也认', () => {
    window.history.pushState({}, '', '/admin/');
    expect(readView()).toBe('admin');
  });

  it('#/admin 哈希也认（静态托管没配 rewrite 时的兜底）', () => {
    window.history.pushState({}, '', '/');
    window.location.hash = '#/admin';
    expect(readView()).toBe('admin');
    window.location.hash = '';
  });

  it('普通路径回工作台', () => {
    window.history.pushState({}, '', '/');
    expect(readView()).toBe('workspace');
  });

  it('/administrator 不能被误判为管理端', () => {
    window.history.pushState({}, '', '/administrator');
    expect(readView()).toBe('workspace');
  });
});

describe('fmtTokens', () => {
  it('万/M 分级', () => {
    expect(fmtTokens(999)).toBe('999');
    expect(fmtTokens(12_345)).toBe('1.2w');
    expect(fmtTokens(1_500_000)).toBe('1.5M');
  });
});
