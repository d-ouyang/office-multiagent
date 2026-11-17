import { describe, expect, it } from 'vitest';

import { ApiError, describeError, parseApiError } from './apiError';

describe('parseApiError', () => {
  it('解析 FastAPI 的 {detail:{code,message}}', () => {
    const e = parseApiError(429, {
      detail: { code: 'BALANCE_INSUFFICIENT', message: '钱包余额不足：余额 ¥0，本次预估 2986' },
    });
    expect(e.status).toBe(429);
    expect(e.code).toBe('BALANCE_INSUFFICIENT');
    expect(e.message).toContain('2986');
  });

  it('解析网关的 {error:{code,message}}', () => {
    const e = parseApiError(400, { error: { code: 'BAD_CREDENTIALS', message: '用户名或密码错误' } });
    expect(e.code).toBe('BAD_CREDENTIALS');
    expect(e.message).toBe('用户名或密码错误');
  });

  it('detail 是字符串时直接当 message', () => {
    expect(parseApiError(500, { detail: 'Internal Server Error' }).message).toBe('Internal Server Error');
  });

  it('body 为空时退化为状态码文案（不抛错）', () => {
    expect(parseApiError(502, null).message).toBe('请求失败（HTTP 502）');
    expect(parseApiError(500, 'not json').message).toBe('请求失败（HTTP 500）');
  });
});

describe('describeError', () => {
  it('余额不足：标题说清后果，正文保留金额，hint 给下一步', () => {
    const n = describeError(
      new ApiError(429, 'BALANCE_INSUFFICIENT', '钱包余额不足：余额 ¥0，本次预估 2986')
    );
    expect(n.kind).toBe('warning');
    expect(n.title).toContain('余额不足');
    expect(n.message).toContain('2986');
    expect(n.hint).toContain('重发');
  });

  it('单任务上限：warning + 拆分建议', () => {
    const n = describeError(new ApiError(429, 'TOKEN_LIMIT_REACHED', '已达单任务上限'));
    expect(n.kind).toBe('warning');
    expect(n.title).toContain('单任务上限');
    expect(n.hint).toContain('拆小');
  });

  it('401 → 登录过期', () => {
    expect(describeError(new ApiError(401, '', 'jwt expired')).title).toContain('登录已过期');
  });

  it('5xx → 服务暂时不可用', () => {
    expect(describeError(new ApiError(503, '', 'busy')).title).toContain('服务暂时不可用');
  });

  it('网络错误（fetch 失败）单独识别', () => {
    expect(describeError(new TypeError('Failed to fetch')).title).toContain('连不上');
  });

  it('绝不把 HTTP 状态码当标题——那是实现细节，对用户没有行动指示', () => {
    const n = describeError(new ApiError(429, '', 'HTTP 429'));
    expect(n.title).not.toContain('429');
    expect(n.title).not.toContain('HTTP');
  });
});
