// 2.1.0 P1-1 HITL：补充输入卡片——选项选择 / 文本回答 / 上传文件名聚合 / 提交回调。
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import AskUserCard from './AskUserCard';

const ask = {
  question: '需要上传销售数据文件（csv/xlsx）',
  options: ['用数据库订单数据', '我来上传文件'],
  need_file: true,
  file_hint: '带表头的 csv',
};

describe('AskUserCard', () => {
  it('渲染问题、选项与文件提示', () => {
    render(<AskUserCard ask={ask} onSubmit={vi.fn()} onUploadFile={vi.fn()} />);
    expect(screen.getByText(ask.question)).toBeTruthy();
    expect(screen.getByText('文件要求：带表头的 csv')).toBeTruthy();
    expect(screen.getByRole('button', { name: '用数据库订单数据' })).toBeTruthy();
  });

  it('点选项即可提交（answer=选项文本）', async () => {
    const onSubmit = vi.fn();
    render(<AskUserCard ask={ask} onSubmit={onSubmit} onUploadFile={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: '用数据库订单数据' }));
    fireEvent.click(screen.getByRole('button', { name: '提交并继续' }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('用数据库订单数据', []));
  });

  it('上传文件后提交，文件名进 attachments', async () => {
    const onSubmit = vi.fn();
    const onUploadFile = vi.fn().mockResolvedValue('sales.csv');
    render(<AskUserCard ask={ask} onSubmit={onSubmit} onUploadFile={onUploadFile} />);
    const input = screen.getByLabelText('上传文件');
    fireEvent.change(input, { target: { files: [new File(['x'], 'sales.csv')] } });
    await waitFor(() => expect(screen.getByText(/已上传：sales\.csv/)).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: '提交并继续' }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('', ['sales.csv']));
  });

  it('无回答且无文件时提交按钮禁用', () => {
    render(<AskUserCard ask={{ ...ask, need_file: false }} onSubmit={vi.fn()} onUploadFile={vi.fn()} />);
    expect((screen.getByRole('button', { name: '提交并继续' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
