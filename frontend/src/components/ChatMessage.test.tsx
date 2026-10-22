import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import ChatMessage from './ChatMessage';
import type { StreamEvent } from '../types';

afterEach(() => cleanup());

const clock = new Date(2026, 9, 21, 22, 1, 0).getTime();

const ev = (type: StreamEvent['type'], data: Record<string, unknown>, ts: number, seq = 1): StreamEvent => ({
  type,
  run_id: 'r',
  turn_id: 't',
  seq,
  ts,
  data,
});

describe('用户消息操作', () => {
  it('气泡下方显示提问时间，编辑和复制是图标', () => {
    render(<ChatMessage index={0} msg={{ role: 'user', text: '你好', createdAt: clock }} onEditSubmit={() => true} />);
    expect(screen.getByText('你好')).toBeInTheDocument();
    expect(screen.getByText('22:01')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '编辑' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '复制' })).toBeInTheDocument();
    expect(screen.queryByText('编辑')).toBeNull();
  });

  it('编辑展开为可取消的输入框', () => {
    render(<ChatMessage index={1} msg={{ role: 'user', text: '原问题', createdAt: clock }} onEditSubmit={() => true} />);
    fireEvent.click(screen.getByRole('button', { name: '编辑' }));
    expect(screen.getByLabelText('编辑提问')).toHaveValue('原问题');
    expect(screen.getByText(/重新开始对话/)).toBeInTheDocument();
    fireEvent.click(screen.getByText('取消'));
    expect(screen.queryByText(/重新开始对话/)).toBeNull();
    expect(screen.getByText('原问题')).toBeInTheDocument();
  });

  it('气泡在正文后面标出附带文件，点击交给预览', () => {
    const onPreview = vi.fn();
    render(
      <ChatMessage
        index={0}
        msg={{ role: 'user', text: '总结一下', attachments: ['白骨塔·正文.md'], attachmentPaths: ['dev/白骨塔·正文.md'], createdAt: clock }}
        onPreview={onPreview}
      />,
    );
    expect(screen.getByText('附带文件')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '白骨塔·正文.md' }));
    expect(onPreview).toHaveBeenCalledWith('dev/白骨塔·正文.md');
  });
});

describe('回复信息行', () => {
  it('完成后显示复制、点赞、点踩、用量、模型、时间和耗时', () => {
    render(
      <ChatMessage
        index={1}
        msg={{
          role: 'assistant',
          createdAt: clock,
          events: [
            ev('content_delta', { delta: '年假五天' }, 1000, 1),
            ev('done', { status: 'single', tokens_used: 3011, model: 'glm-5.3-flash-sf' }, 4200, 2),
          ],
        }}
      />,
    );
    expect(screen.getByRole('button', { name: '复制' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '点赞' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '点踩' })).toBeInTheDocument();
    expect(screen.getByText('共消耗 3,011')).toBeInTheDocument();
    expect(screen.getByText('GLM-5.3-Flash')).toBeInTheDocument();
    expect(screen.getByText('22:01')).toBeInTheDocument();
    expect(screen.getByText('耗时 3.2s')).toBeInTheDocument();
  });

  it('trace 没有模型时用消息上的 model，排在消耗后面', () => {
    render(
      <ChatMessage
        index={1}
        msg={{ role: 'assistant', content: '好', createdAt: clock, model: 'deepseek-chat', tokens: 1200 }}
      />,
    );
    const row = screen.getByText(/共消耗/).parentElement;
    expect(row?.textContent).toContain('共消耗 1,200');
    expect(row?.textContent).toContain('DeepSeek V3');
    expect(row?.textContent?.indexOf('共消耗')).toBeLessThan(row?.textContent?.indexOf('DeepSeek V3') ?? -1);
  });

  it('点赞只切换选中态', () => {
    render(
      <ChatMessage
        index={1}
        msg={{ role: 'assistant', content: '好的', createdAt: clock }}
      />,
    );
    const up = screen.getByRole('button', { name: '点赞' });
    fireEvent.click(up);
    expect(up).toHaveAttribute('data-on');
    fireEvent.click(screen.getByRole('button', { name: '点踩' }));
    expect(up).not.toHaveAttribute('data-on');
    expect(screen.getByRole('button', { name: '点踩' })).toHaveAttribute('data-on');
  });

  it('流式过程中不显示信息行', () => {
    render(
      <ChatMessage
        index={1}
        msg={{ role: 'assistant', streaming: true, events: [ev('content_delta', { delta: '…' }, 1)] }}
      />,
    );
    expect(screen.queryByText(/共消耗/)).toBeNull();
  });
});

describe('复制提示', () => {
  it('写入剪贴板', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<ChatMessage index={0} msg={{ role: 'user', text: '要复制的话', createdAt: clock }} />);
    fireEvent.click(screen.getByRole('button', { name: '复制' }));
    expect(writeText).toHaveBeenCalledWith('要复制的话');
  });
});
