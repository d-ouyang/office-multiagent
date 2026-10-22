import { describe, expect, it } from 'vitest';

import { fmtCtx, toPromptModel } from './ModelPicker';

describe('fmtCtx', () => {
  it('整千位按千显示，二进制窗口按 1024 显示', () => {
    expect(fmtCtx(128000)).toBe('128K');
    expect(fmtCtx(163840)).toBe('160K');
    expect(fmtCtx(262144)).toBe('256K');
    expect(fmtCtx(1048576)).toBe('1M');
  });

  it('能力只标思考和视觉', () => {
    const row = toPromptModel({
      id: 'qwen3.5-9b-sf',
      name: 'Qwen3.5-9B',
      provider: 'siliconflow',
      multimodal_input: true,
      context_window: 262144,
      supports_reasoning: true,
      description: '9B · 工具 · 续写',
    });
    expect(row.tag).toBe('256K · 思考 · 视觉');
    expect(row).not.toHaveProperty('description');
  });
});