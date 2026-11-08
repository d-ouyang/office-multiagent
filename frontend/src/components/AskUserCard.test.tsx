// 2.1.0 P1-1 HITL：多问题向导——单题选项提交 / 多题 n/N 收集 / 跳过 / 其他补充 / 收起。
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import AskUserCard from './AskUserCard';

const singleAsk = {
  questions: [
    {
      question: '需要上传销售数据文件（csv/xlsx）',
      options: ['用数据库订单数据', '我来上传文件'],
      need_file: false,
      file_hint: '',
    },
  ],
};

const multiAsk = {
  questions: [
    { question: '数据来源？', options: ['数据库订单', '我上传文件'], need_file: false, file_hint: '' },
    { question: '统计口径？', options: ['按月汇总', '按门店'], need_file: false, file_hint: '' },
  ],
};

describe('AskUserCard', () => {
  it('单问题：点选项直接提交（answer=选项文本）', async () => {
    const onSubmit = vi.fn();
    render(<AskUserCard ask={singleAsk} onSubmit={onSubmit} onUploadFile={vi.fn()} onDismiss={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /用数据库订单数据/ }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('用数据库订单数据', []));
  });

  it('多问题：n/N 逐题收集，全部答完后一次提交（Q/A 段落聚合）', async () => {
    const onSubmit = vi.fn();
    render(<AskUserCard ask={multiAsk} onSubmit={onSubmit} onUploadFile={vi.fn()} onDismiss={vi.fn()} />);
    expect(screen.getByText('1/2')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /数据库订单/ }));
    await waitFor(() => expect(screen.getByText('2/2')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /按月汇总/ }));
    // 最后一题答完 → 点「提交并继续」一次性提交
    fireEvent.click(screen.getByRole('button', { name: '提交并继续' }));
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith(
        '问题：数据来源？\n回答：数据库订单\n\n问题：统计口径？\n回答：按月汇总',
        [],
      ),
    );
  });

  it('跳过的问题按「（跳过）」聚合', async () => {
    const onSubmit = vi.fn();
    render(<AskUserCard ask={multiAsk} onSubmit={onSubmit} onUploadFile={vi.fn()} onDismiss={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: '跳过' })); // 第 1 题跳过 → 自动到第 2 题
    await waitFor(() => expect(screen.getByText('2/2')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /按门店/ }));
    fireEvent.click(screen.getByRole('button', { name: '提交并继续' }));
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith(
        '问题：数据来源？\n回答：（跳过）\n\n问题：统计口径？\n回答：按门店',
        [],
      ),
    );
  });

  it('「其他补充」展开输入框，输入后提交', async () => {
    const onSubmit = vi.fn();
    render(<AskUserCard ask={singleAsk} onSubmit={onSubmit} onUploadFile={vi.fn()} onDismiss={vi.fn()} />);
    fireEvent.click(screen.getByText('其他补充…'));
    fireEvent.change(screen.getByLabelText('其他补充'), { target: { value: '先按订单表统计' } });
    fireEvent.click(screen.getByLabelText('确认补充'));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('先按订单表统计', []));
  });

  it('×收起后任务仍待确认（onDismiss 回调，恢复条由父级渲染）', () => {
    const onDismiss = vi.fn();
    render(<AskUserCard ask={singleAsk} onSubmit={vi.fn()} onUploadFile={vi.fn()} onDismiss={onDismiss} />);
    fireEvent.click(screen.getByLabelText('收起'));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
