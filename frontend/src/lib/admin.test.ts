// p6.26：管理端路由与用量格式化（纯函数，jsdom 环境）
import { readView } from '../App';
import { fmtTokens } from '../pages/AdminPanels';

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

// p6.28b：分页页码窗口
import { pageWindow } from '../components/ui/Pager';

describe('pageWindow（分页页码折叠）', () => {
  it('总页数 ≤7 时全展开', () => {
    expect(pageWindow(1, 5)).toEqual([1, 2, 3, 4, 5]);
    expect(pageWindow(3, 7)).toEqual([1, 2, 3, 4, 5, 6, 7]);
  });
  it('靠前：左侧不折叠', () => {
    expect(pageWindow(2, 20)).toEqual([1, 2, 3, 4, '…', 20]);
  });
  it('居中：两侧折叠', () => {
    expect(pageWindow(10, 20)).toEqual([1, '…', 8, 9, 10, 11, 12, '…', 20]);
  });
  it('靠后：右侧不折叠', () => {
    expect(pageWindow(19, 20)).toEqual([1, '…', 17, 18, 19, 20]);
  });
});

// p6.28a：审计明细人话化
import { renderDetail } from '../pages/AdminPanels';

describe('renderDetail（审计明细翻译）', () => {
  it('充值明细', () => {
    const lines = renderDetail('admin.recharge', { amount: 5000, balance_after: 5100, note: '月度补充' });
    expect(lines.join(' ')).toContain('5,000');
    expect(lines.join(' ')).toContain('月度补充');
  });
  it('登录失败给原因，不暴露任何敏感字段', () => {
    const lines = renderDetail('admin.login.failure', { reason: 'bad_credentials' });
    expect(lines[0]).toContain('用户名或密码错误');
  });
  it('未知动作返回空（不硬编）', () => {
    expect(renderDetail('admin.unknown', { x: 1 })).toEqual([]);
    expect(renderDetail('admin.recharge', null)).toEqual([]);
  });
});
