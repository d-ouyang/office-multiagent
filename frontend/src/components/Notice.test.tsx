import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import Notice from './Notice';

afterEach(() => cleanup());

describe('Notice（v2.4.1 统一提示条）', () => {
  it('按字段渲染标题/正文/提示', () => {
    render(
      <Notice
        notice={{ kind: 'warning', title: '余额不足，本次任务没能开始', message: '余额 ¥0，本次预估 2986', hint: '充值后重发' }}
      />
    );
    expect(screen.getByText('余额不足，本次任务没能开始')).toBeInTheDocument();
    expect(screen.getByText('余额 ¥0，本次预估 2986')).toBeInTheDocument();
    expect(screen.getByText('充值后重发')).toBeInTheDocument();
    expect(screen.getByRole('alert').className).toContain('notice-warning');
  });

  it('kind 决定样式类', () => {
    const { rerender } = render(<Notice notice={{ kind: 'error', title: 'x' }} />);
    expect(screen.getByRole('alert').className).toContain('notice-error');
    rerender(<Notice notice={{ kind: 'info', title: 'x' }} />);
    expect(screen.getByRole('alert').className).toContain('notice-info');
  });

  it('关闭按钮触发 onClose，不传时不渲染按钮', () => {
    const onClose = vi.fn();
    const { rerender } = render(<Notice notice={{ kind: 'error', title: 'x' }} onClose={onClose} />);
    fireEvent.click(screen.getByLabelText('关闭提示'));
    expect(onClose).toHaveBeenCalledTimes(1);

    rerender(<Notice notice={{ kind: 'error', title: 'x' }} />);
    expect(screen.queryByLabelText('关闭提示')).toBeNull();
  });

  it('可选操作按钮', () => {
    const onClick = vi.fn();
    render(<Notice notice={{ kind: 'warning', title: '余额不足' }} action={{ label: '去充值', onClick }} />);
    fireEvent.click(screen.getByText('去充值'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
