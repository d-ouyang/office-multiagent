import { describe, expect, it } from 'vitest';

import { fmtCtx } from './ModelPicker';

describe('fmtCtx', () => {
  it('整千位按千显示，二进制窗口按 1024 显示', () => {
    expect(fmtCtx(128000)).toBe('128K');
    expect(fmtCtx(163840)).toBe('160K');
    expect(fmtCtx(262144)).toBe('256K');
    expect(fmtCtx(1048576)).toBe('1M');
  });
});