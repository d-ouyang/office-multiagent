// p6.12：会话列表相对时间规则 + 折叠/展开（默认 10 条，"查看更多 (N)"）
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import AppSidebar, { formatSessionTime, type SessionMeta } from './AppSidebar';
import { APP_BLURB, APP_VERSION } from '../version';
import { act } from 'react';

afterEach(() => cleanup());

const NOW = new Date('2026-10-21T12:00:00').getTime();
const min = 60_000;

const user = { employee_id: 'EMP001', username: 'dev', role: 'admin' };

const mkSessions = (n: number, updatedAt = NOW): SessionMeta[] =>
  Array.from({ length: n }, (_, i) => ({ id: `s-${i}`, title: `会话 ${i}`, updatedAt }));

describe('formatSessionTime（p6.12 显示规则）', () => {
  it('1 分钟内显示 HH:MM', () => {
    const t = new Date('2026-10-21T11:59:30').getTime();
    expect(formatSessionTime(t, NOW)).toMatch(/^\d{2}:\d{2}$/);
  });
  it('超过 1 分钟显示 XX分钟前', () => {
    expect(formatSessionTime(NOW - 5 * min, NOW)).toBe('5分钟前');
  });
  it('超过 1 小时显示 XX小时前', () => {
    expect(formatSessionTime(NOW - 3 * 60 * min, NOW)).toBe('3小时前');
  });
  it('超过 1 天显示 XX天前', () => {
    expect(formatSessionTime(NOW - 5 * 24 * 60 * min, NOW)).toBe('5天前');
  });
  it('超过 7 天显示 MM月DD日', () => {
    const t = new Date('2026-10-02T08:00:00').getTime();
    expect(formatSessionTime(t, NOW)).toBe('10月2日');
  });
  it('非法时间戳返回空串', () => {
    expect(formatSessionTime(NaN, NOW)).toBe('');
    expect(formatSessionTime(0, NOW)).toBe('');
  });
});

describe('AppSidebar 会话分页展开（p6.12c：每次 10 条）', () => {
  it('≤10 条全部显示，无"查看更多/收起"', () => {
    render(<AppSidebar sessions={mkSessions(10)} currentId="s-0" onSelect={() => {}} onNew={() => {}} user={user} onLogout={() => {}} />);
    expect(screen.getByText('会话 9')).toBeInTheDocument();
    expect(screen.queryByText(/查看更多/)).toBeNull();
    expect(screen.queryByText('收起')).toBeNull();
  });

  it('>10 条默认只显示 10 条，"查看更多 (剩余N)"显示未展开条数', () => {
    render(<AppSidebar sessions={mkSessions(23)} currentId="s-0" onSelect={() => {}} onNew={() => {}} user={user} onLogout={() => {}} />);
    expect(screen.getByText('会话 9')).toBeInTheDocument();
    expect(screen.queryByText('会话 10')).toBeNull(); // 第 11 条被折叠
    expect(screen.getByText('查看更多 (13)')).toBeInTheDocument(); // 剩余 13 条
    expect(screen.queryByText('收起')).toBeNull(); // 初始折叠态无收起
  });

  it('点击"查看更多"加载下一条 10 条，未完显示"查看更多 (3) | 收起"', () => {
    render(<AppSidebar sessions={mkSessions(23)} currentId="s-0" onSelect={() => {}} onNew={() => {}} user={user} onLogout={() => {}} />);
    act(() => {
      fireEvent.click(screen.getByText('查看更多 (13)'));
    });
    expect(screen.getByText('会话 19')).toBeInTheDocument(); // 第二页最后一条
    expect(screen.queryByText('会话 20')).toBeNull();
    expect(screen.getByText('查看更多 (3)')).toBeInTheDocument();
    expect(screen.getByText('收起')).toBeInTheDocument();
  });

  it('再次点击全部展示完毕 → 只剩"收起"', () => {
    render(<AppSidebar sessions={mkSessions(23)} currentId="s-0" onSelect={() => {}} onNew={() => {}} user={user} onLogout={() => {}} />);
    act(() => {
      fireEvent.click(screen.getByText('查看更多 (13)'));
    });
    act(() => {
      fireEvent.click(screen.getByText('查看更多 (3)'));
    });
    expect(screen.getByText('会话 22')).toBeInTheDocument(); // 最后一条可见
    expect(screen.queryByText(/查看更多/)).toBeNull();
    expect(screen.getByText('收起')).toBeInTheDocument();
  });

  it('收起恢复默认 10 条', () => {
    render(<AppSidebar sessions={mkSessions(23)} currentId="s-0" onSelect={() => {}} onNew={() => {}} user={user} onLogout={() => {}} />);
    act(() => {
      fireEvent.click(screen.getByText('查看更多 (13)'));
    });
    act(() => {
      fireEvent.click(screen.getByText('收起'));
    });
    expect(screen.getByText('会话 9')).toBeInTheDocument();
    expect(screen.queryByText('会话 10')).toBeNull();
    expect(screen.getByText('查看更多 (13)')).toBeInTheDocument();
    expect(screen.queryByText('收起')).toBeNull();
  });
});

describe('会话操作', () => {
  it('点击更多操作才出现菜单，删除要弹窗确认', () => {
    const onDelete = vi.fn();
    render(<AppSidebar sessions={mkSessions(1)} currentId="s-0" onSelect={() => {}} onNew={() => {}} onDelete={onDelete} user={user} onLogout={() => {}} />);
    const more = screen.getByRole('button', { name: '更多操作' });
    expect(more).toHaveAttribute('title', '更多操作');
    expect(screen.queryByRole('button', { name: '置顶' })).toBeNull();
    fireEvent.click(more);
    expect(screen.getByRole('button', { name: '置顶' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重命名' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '删除会话' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('确认删除会话「会话 0」？');
    expect(screen.getByText('该会话下的全部对话消息会一并删除，且无法恢复。')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(onDelete).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }));
    fireEvent.click(screen.getByRole('button', { name: '删除会话' }));
    fireEvent.click(screen.getByRole('button', { name: '删除' }));
    expect(onDelete).toHaveBeenCalledWith('s-0');
  });
});

describe('侧栏简介与版本', () => {
  it('展示锅圈 Agent、项目简介和当前版本号', () => {
    render(<AppSidebar sessions={[]} currentId="" onSelect={() => {}} onNew={() => {}} user={user} onLogout={() => {}} />);
    expect(screen.getByText('锅圈 Agent')).toBeInTheDocument();
    expect(screen.getByText(APP_BLURB)).toBeInTheDocument();
    expect(screen.getByText('office-multiagent')).toBeInTheDocument();
    expect(screen.getByText(APP_VERSION)).toBeInTheDocument();
    expect(screen.queryByText('管理（用户与额度）')).toBeNull();
  });

  it('点用户行打开个人中心，额度进入用量弹窗，退出需确认', () => {
    let loggedOut = 0;
    render(<AppSidebar sessions={[]} currentId="" onSelect={() => {}} onNew={() => {}} user={user} balance={100000} onLogout={() => { loggedOut += 1; }} onOpenAdmin={() => {}} />);
    act(() => {
      fireEvent.click(screen.getByRole('button', { name: /dev/ }));
    });
    expect(screen.getByText('修改密码')).toBeInTheDocument();
    expect(screen.getByText('管理端')).toBeInTheDocument();
    expect(screen.getByText('100,000')).toBeInTheDocument();
    act(() => {
      fireEvent.click(screen.getByRole('button', { name: /剩余额度/ }));
    });
    expect(screen.getByRole('dialog', { name: '用量明细' })).toBeInTheDocument();
    act(() => {
      fireEvent.click(screen.getByRole('button', { name: '关闭' }));
    });
    act(() => {
      fireEvent.click(screen.getByRole('button', { name: /dev/ }));
    });
    expect(screen.queryByRole('button', { name: '退出' })).toBeNull();
    act(() => {
      fireEvent.click(screen.getByRole('button', { name: '退出登录' }));
    });
    expect(loggedOut).toBe(0);
    expect(screen.getByText('确定退出登录？')).toBeInTheDocument();
    act(() => {
      fireEvent.click(screen.getByRole('button', { name: '退出' }));
    });
    expect(loggedOut).toBe(1);
  });
});
