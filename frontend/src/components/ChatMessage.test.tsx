import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import ChatMessage from './ChatMessage';
import type { StreamEvent } from '../types';
import { act } from 'react';

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
          id: 11,
          createdAt: clock,
          events: [
            ev('content_delta', { delta: '年假五天' }, 1000, 1),
            ev('done', { status: 'single', tokens_used: 3011, model: 'glm-5.3-flash-sf' }, 4200, 2),
          ],
        }}
        onFeedbackSubmit={() => Promise.resolve(null)}
        onFeedbackCancel={() => Promise.resolve(true)}
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

  it('没有消息 id 或回调时不渲染反馈按钮（流式刚结束的本地消息）', () => {
    render(
      <ChatMessage index={1} msg={{ role: 'assistant', content: '好', createdAt: clock }} />,
    );
    expect(screen.getByRole('button', { name: '复制' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '点赞' })).toBeNull();
    expect(screen.queryByRole('button', { name: '点踩' })).toBeNull();
  });

  it('trace 没有模型时用消息上的 model，排在消耗后面', () => {
    render(
      <ChatMessage
        index={1}
        msg={{ role: 'assistant', content: '好', createdAt: clock, model: 'deepseek-chat', tokens: 1200 }}
      />,
    );
    // p6.45：「共消耗」外包了一层 .reply-tokens（装逐步用量浮窗），取整行用 closest
    const row = screen.getByText(/共消耗/).closest('.reply-stats');
    expect(row?.textContent).toContain('共消耗 1,200');
    expect(row?.textContent).toContain('DeepSeek V3');
    expect(row?.textContent?.indexOf('共消耗')).toBeLessThan(row?.textContent?.indexOf('DeepSeek V3') ?? -1);
  });

  it('点赞直接落库，激活后再点 = 取消', async () => {
    const onSubmit = vi.fn(() => Promise.resolve({ rating: 'like', tags: [], comment: null, at: null }));
    const onCancel = vi.fn(() => Promise.resolve(true));
    render(
      <ChatMessage
        index={1}
        msg={{ role: 'assistant', id: 5, content: '好的', createdAt: clock }}
        onFeedbackSubmit={onSubmit}
        onFeedbackCancel={onCancel}
      />,
    );
    const up = screen.getByRole('button', { name: '点赞' });
    await act(async () => {
      fireEvent.click(up);
    });
    expect(onSubmit).toHaveBeenCalledWith(5, 'like', [], '');
    expect(await screen.findByRole('button', { name: '取消点赞' })).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '取消点赞' }));
    });
    expect(onCancel).toHaveBeenCalledWith(5);
  });

  it('点踩走弹窗：tag 多选 + 其他原因展开输入，提交带原因', async () => {
    const onSubmit = vi.fn(() => Promise.resolve({ rating: 'dislike', tags: ['数据或数字有误'], comment: '', at: null }));
    render(
      <ChatMessage
        index={1}
        msg={{ role: 'assistant', id: 6, content: '答案', createdAt: clock }}
        onFeedbackSubmit={onSubmit}
        onFeedbackCancel={() => Promise.resolve(true)}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '点踩' }));
    const dialog = await screen.findByRole('dialog', { name: '意见反馈' });
    expect(dialog).toHaveTextContent('抱歉，这次回答没能帮到你');
    // 无原因时不能提交
    expect(screen.getByRole('button', { name: '提交反馈' })).toBeDisabled();
    // 选 tag + 其他原因 → 输入框出现，0/200 计数
    fireEvent.click(screen.getByRole('button', { name: '数据或数字有误' }));
    fireEvent.click(screen.getByRole('button', { name: '其他原因' }));
    const input = screen.getByLabelText('其他原因');
    await act(async () => {
      fireEvent.change(input, { target: { value: '环比算错了' } });
    });
    expect(screen.getByText('5/200')).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '提交反馈' }));
    });
    expect(onSubmit).toHaveBeenCalledWith(6, 'dislike', ['数据或数字有误', '其他原因'], '环比算错了');
    // 提交成功后弹窗关闭，点踩实心（激活态）
    expect(await screen.findByRole('button', { name: '取消点踩' })).toBeInTheDocument();
  });

  it('激活的点踩再点 = 直接取消；取消后再点踩是新的一次反馈（不回显旧原因）', async () => {
    const onCancel = vi.fn(() => Promise.resolve(true));
    render(
      <ChatMessage
        index={1}
        msg={{
          role: 'assistant',
          id: 7,
          content: '答案',
          createdAt: clock,
          feedback: { rating: 'dislike', tags: ['回答不专业'], comment: '太笼统', at: null },
        }}
        onFeedbackSubmit={() => Promise.resolve(null)}
        onFeedbackCancel={onCancel}
      />,
    );
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '取消点踩' }));
    });
    expect(onCancel).toHaveBeenCalledWith(7);
    expect(screen.getByRole('button', { name: '点踩' })).toBeInTheDocument();

    // 取消后再点踩 = 新的一次反馈：弹窗干净（旧原因不回显，覆盖逻辑由服务端流水负责）
    fireEvent.click(screen.getByRole('button', { name: '点踩' }));
    await screen.findByRole('dialog', { name: '意见反馈' });
    expect(screen.getByRole('button', { name: '回答不专业' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.queryByLabelText('其他原因')).toBeNull();
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

describe('过程顺序', () => {
  it('阶段回答留在过程里，最后一段才显示为结果', async () => {
    render(
      <ChatMessage
        index={1}
        msg={{
          role: 'assistant',
          events: [
            ev('thinking_delta', { delta: '先看表' }, 1, 1),
            ev('content_delta', { delta: '阶段：上海有数据' }, 2, 2),
            ev('tool_call_start', { tool_id: 'a', name: 'analyze_table', input: { clean_id: 'c-1' } }, 3, 3),
            ev('tool_call_end', { tool_id: 'a', success: true, duration_ms: 20 }, 4, 4),
            ev('content_delta', { delta: '最终：上海合计 12' }, 5, 5),
          ],
        }}
      />,
    );
    expect(await screen.findByText(/最终/)).toBeInTheDocument();
    expect(screen.queryByText(/阶段/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /已完成/ }));
    expect(await screen.findByText(/阶段/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /运行 analyze_table/ })).toBeInTheDocument();
  });

  it('深度思考的耗时紧跟标题，字数仍在右侧', async () => {
    render(
      <ChatMessage
        index={1}
        msg={{
          role: 'assistant',
          events: [
            ev('thinking_delta', { delta: '先' }, 1000, 1),
            ev('thinking_delta', { delta: '想' }, 2500, 2),
            ev('content_delta', { delta: '结论' }, 3000, 3),
          ],
        }}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /已完成/ }));
    const think = await screen.findByRole('button', { name: /深度思考 1\.5s/ });
    expect(think).toHaveTextContent('2 字');
    expect(think.textContent?.indexOf('1.5s')).toBeLessThan(think.textContent?.indexOf('2 字') ?? 0);
  });
});

describe('生成文件', () => {
  it('产物出现在正文下，点击交给预览', () => {
    const onPreview = vi.fn();
    render(
      <ChatMessage
        index={1}
        msg={{
          role: 'assistant',
          events: [
            ev('content_delta', { delta: '已写好。' }, 1),
            ev('artifact', { asset_id: 'w-1', type: 'md', name: '周报.md', storage_url: '_out/w-1.md' }, 2),
            ev('done', { status: 'done' }, 3),
          ],
        }}
        onPreview={onPreview}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '周报.md' }));
    expect(onPreview).toHaveBeenCalledWith('_out/w-1.md');
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
