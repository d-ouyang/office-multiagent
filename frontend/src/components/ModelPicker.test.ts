import { describe, expect, it } from 'vitest';

import { fmtCtx, toPromptModel } from './ModelPicker';

describe('fmtCtx', () => {
  it('整千位按千显示，二进制窗口按 1024 显示', () => {
    expect(fmtCtx(128000)).toBe('128K');
    expect(fmtCtx(163840)).toBe('160K');
    expect(fmtCtx(262144)).toBe('256K');
    expect(fmtCtx(1048576)).toBe('1M');
  });

  it('推理和视觉进标签，其余能力进说明', () => {
    const row = toPromptModel({
      id: 'longcat-2.0-sf',
      name: 'LongCat-2.0',
      provider: 'siliconflow',
      multimodal_input: false,
      context_window: 1048576,
      supports_reasoning: true,
      description: '长说明',
      highlights: ['1.6T MoE', '工具', '续写'],
    });
    expect(row.tag).toBe('1M · 思考');
    expect(row.description).toBe('1.6T MoE · 工具 · 续写');
  });
});