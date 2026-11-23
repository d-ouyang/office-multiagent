// v2.4.5：「待确认」收敛——latestPausedTask 只认该会话最新一条任务。
//
// 事故形态：会话里先有一条 paused_input（没答），之后又跑了几轮 done。
// 旧实现从最近 10 条里 find 任意 paused → 刷新一次弹一次同一张问题卡，
// 侧栏也永远挂「待确认」。语义上只有"最新那条还停着"才需要用户处理。
import { afterEach, describe, expect, it, vi } from 'vitest';

import { latestPausedTask } from './api';

function stubTasks(tasks: Array<Record<string, unknown>>): void {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ tasks }),
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('latestPausedTask', () => {
  it('最新一条是 done → 不认为有待确认（老 paused 作废）', async () => {
    stubTasks([
      { id: 't-latest', session_id: 's-1', status: 'done', text: '' },
      { id: 't-old-paused', session_id: 's-1', status: 'paused_input', text: '' },
    ]);

    await expect(latestPausedTask('s-1')).resolves.toBeNull();
  });

  it('最新一条是 paused_input → 返回它本身', async () => {
    stubTasks([
      { id: 't-latest', session_id: 's-1', status: 'paused_input', text: '导明细' },
      { id: 't-old-done', session_id: 's-1', status: 'done', text: '' },
    ]);

    const task = await latestPausedTask('s-1');

    expect(task?.id).toBe('t-latest');
  });

  it('最新一条是 failed → 返回（可重试横幅）', async () => {
    stubTasks([{ id: 't-failed', session_id: 's-1', status: 'failed', text: '' }]);

    const task = await latestPausedTask('s-1');

    expect(task?.id).toBe('t-failed');
  });

  it('最新一条是 superseded（已作废）→ 不弹', async () => {
    stubTasks([
      { id: 't-superseded', session_id: 's-1', status: 'superseded', text: '' },
      { id: 't-older-paused', session_id: 's-1', status: 'paused_input', text: '' },
    ]);

    await expect(latestPausedTask('s-1')).resolves.toBeNull();
  });

  it('空列表 → null', async () => {
    stubTasks([]);

    await expect(latestPausedTask('s-1')).resolves.toBeNull();
  });
});
