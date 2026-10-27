// p6.26：管理端路由与用量格式化（纯函数，jsdom 环境）
import { readView } from '../App';
import { fmtTokens, renderDetail } from '../pages/AdminPanels';
import { ADMIN_TABS, readAdminTab } from '../admin/nav';
import { fmtDuration, fmtShanghai } from '../admin/format';
import { DRAWER_WIDTH, PAGE_SIZE } from '../admin/AdminListPage';
import { TASK_COLUMN_TITLES, TASK_COL_WIDTH } from '../admin/TasksTab';
import { copyAdminText } from '../admin/ellipsis';
import { humanizeAdminError, isUglyAdminError } from '../admin/errors';
import { flowPathOf } from '../admin/FlowPathSvg';
import { useDebouncedValue } from '../admin/useDebouncedValue';
import { act, renderHook } from '@testing-library/react';

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

describe('ADMIN_TABS', () => {
  it('一级入口固定六个，没有分组页（p2.3 增加意见反馈）', () => {
    expect(ADMIN_TABS.map((t) => t.key)).toEqual(['overview', 'tasks', 'users', 'pools', 'audit', 'feedback']);
  });
});

describe('readAdminTab', () => {
  it('默认概览，旧 hash 折叠进新导航', () => {
    expect(readAdminTab('')).toBe('overview');
    expect(readAdminTab('#usage')).toBe('overview');
    expect(readAdminTab('#system')).toBe('overview');
    expect(readAdminTab('#runs')).toBe('tasks');
    expect(readAdminTab('#users')).toBe('users');
  });
});

describe('上海时间与耗时', () => {
  it('ISO 转 Asia/Shanghai', () => {
    expect(fmtShanghai('2026-10-25T00:00:00Z')).toBe('2026-10-25 08:00:00');
  });
  it('耗时格式', () => {
    expect(fmtDuration(null)).toBe('—');
    expect(fmtDuration(800)).toBe('800ms');
    expect(fmtDuration(12_000)).toBe('12s');
    expect(fmtDuration(125_000)).toBe('2m 5s');
  });
});

// p6.28a：审计明细人话化

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
  it('模型更新写字段名', () => {
    expect(renderDetail('admin.model.update', { fields: ['name', 'max_output'] }).join(' ')).toContain('name');
  });
  it('新建模型写实际调用名', () => {
    const lines = renderDetail('admin.model.create', { api_model: 'deepseek-ai/DeepSeek-V4.1-Flash', provider: 'siliconflow' });
    expect(lines.join(' ')).toContain('deepseek-ai/DeepSeek-V4.1-Flash');
  });
});

describe('humanizeAdminError', () => {
  it('把 JSON 解析垃圾收成中文', () => {
    expect(isUglyAdminError('Unexpected token \'|\', "|internalS"... is not valid JSON')).toBe(true);
    expect(humanizeAdminError(new Error('Unexpected token "|" is not valid JSON'), '加载用户列表失败，请稍后重试'))
      .toBe('加载用户列表失败，请稍后重试');
    expect(humanizeAdminError(new Error('FORBIDDEN'))).toBe('需要管理员权限');
  });
});

describe('flowPathOf', () => {
  it('优先用后端 flow_path', () => {
    expect(flowPathOf({ nodes: [], path: ['received'], flow_path: ['received', 'tools'] })).toEqual(['received', 'tools']);
    expect(flowPathOf({ nodes: [], path: ['received'] })).toEqual(['received']);
  });
});

describe('PAGE_SIZE', () => {
  it('固定 20，页面不提供每页条数选择', () => {
    expect(PAGE_SIZE).toBe(20);
  });
});

describe('DRAWER_WIDTH', () => {
  it('抽屉紧凑宽度（p2.5 对齐 rag 管理端，720px 放得下流程图与流水表）', () => {
    expect(DRAWER_WIDTH).toBe('min(720px, 80vw)');
  });
});

describe('任务监控列', () => {
  it('没有任务原因幽灵列，操作列有标题', () => {
    expect(TASK_COLUMN_TITLES).toEqual([
      '用户', '工号', '时间', '任务摘要', '任务耗时', '状态', '任务id', '会话id', '消耗token', '操作',
    ]);
    expect(TASK_COLUMN_TITLES).not.toContain('任务原因');
  });
  it('只有摘要弹性；id 列按 14px 字号放下完整 16/18 位（p2.5 收窄）', () => {
    expect('summary' in TASK_COL_WIDTH).toBe(false);
    expect(TASK_COL_WIDTH.username).toBeGreaterThanOrEqual(72);
    expect(TASK_COL_WIDTH.duration).toBeGreaterThanOrEqual(80);
    expect(TASK_COL_WIDTH.token).toBeGreaterThanOrEqual(92);
    expect(TASK_COL_WIDTH.taskId).toBe(152);   // 16 位 hex @14px + padding
    expect(TASK_COL_WIDTH.sessionId).toBe(168); // s- + 16 hex @14px + padding
    expect(TASK_COL_WIDTH.action).toBeGreaterThanOrEqual(88);
  });
});

describe('copyAdminText', () => {
  it('空值和破折号不写剪贴板', async () => {
    const write = vi.fn();
    Object.assign(navigator, { clipboard: { writeText: write } });
    expect(await copyAdminText('')).toBe(false);
    expect(await copyAdminText('—')).toBe(false);
    expect(write).not.toHaveBeenCalled();
  });
  it('有内容则写入剪贴板', async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText: write } });
    expect(await copyAdminText('  task-123  ')).toBe(true);
    expect(write).toHaveBeenCalledWith('task-123');
  });
});

describe('useDebouncedValue', () => {
  it('300ms 后才更新', () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(({ v }) => useDebouncedValue(v, 300), { initialProps: { v: 'a' } });
    expect(result.current).toBe('a');
    rerender({ v: 'ab' });
    expect(result.current).toBe('a');
    act(() => { vi.advanceTimersByTime(300); });
    expect(result.current).toBe('ab');
    vi.useRealTimers();
  });
});
