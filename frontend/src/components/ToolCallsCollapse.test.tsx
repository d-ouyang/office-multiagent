import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import ToolCallsCollapse from './ToolCallsCollapse';
import type { ToolCall } from '../lib/derive';

afterEach(() => cleanup());

const tc = (over: Partial<ToolCall> = {}): ToolCall => ({
  id: 'x',
  name: 'web_search',
  status: 'running',
  input: {},
  ...over,
});

describe('ToolCallsCollapse', () => {
  it('单个 running 工具展示执行中（自动展开，条 + 详情各一处）', () => {
    render(<ToolCallsCollapse toolCalls={[tc()]} isStreaming />);
    expect(screen.getByText('web_search')).toBeInTheDocument();
    // useEffect 会把单个 running 自动展开 → 折叠条与详情都显示"执行中..."
    expect(screen.getAllByText('执行中...').length).toBeGreaterThanOrEqual(1);
  });

  it('完成后折叠为"查看步骤"，点击展开看结果', () => {
    const { rerender } = render(
      <ToolCallsCollapse toolCalls={[tc({ status: 'running' })]} isStreaming />,
    );
    rerender(
      <ToolCallsCollapse toolCalls={[tc({ status: 'completed', result: 'ok' })]} isStreaming={false} />,
    );
    const bar = screen.getByText('查看步骤');
    expect(bar).toBeInTheDocument();
    fireEvent.click(bar); // 展开
    expect(screen.getByText(/结果:/)).toBeInTheDocument();
    expect(screen.getByText('ok')).toBeInTheDocument();
  });

  it('error 状态展开显示失败', () => {
    render(
      <ToolCallsCollapse toolCalls={[tc({ status: 'error', error: 'boom' })]} isStreaming={false} />,
    );
    fireEvent.click(screen.getByText('查看步骤')); // 展开
    expect(screen.getByText('失败')).toBeInTheDocument();
  });

  it('多个工具汇总显示数量', () => {
    render(
      <ToolCallsCollapse
        toolCalls={[
          tc({ id: 'a', status: 'completed' }),
          tc({ id: 'b', name: 'read', status: 'completed' }),
          tc({ id: 'c', name: 'read', status: 'completed' }),
        ]}
        isStreaming={false}
      />,
    );
    expect(screen.getByText('(3)')).toBeInTheDocument();
  });
});
