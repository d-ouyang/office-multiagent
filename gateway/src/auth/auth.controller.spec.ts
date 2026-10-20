/** 登录端点单测（p6.1）——repo/jwt 均 mock，不连真库；密码比对用真 bcrypt 对种子 hash。 */
import { HttpException } from '@nestjs/common';
import { JwtService } from '@nestjs/jwt';
import { Test } from '@nestjs/testing';

import { AuthController } from './auth.controller';
import { UserRepo } from './user-repo';

// init.sql 种子 dev 的真实 bcrypt hash（明文 Office@2026，cost 12）
const DEV_HASH = '$2b$12$bKWdpuPQGPIxCXoWyzhHaeVlvkE3eRXiiuH2Gqp6VOJDrFcVwrJrS';
const DEV_ROW = {
  id: 1, employee_id: 'EMP001', username: 'dev', password_hash: DEV_HASH, role: 'admin',
};

async function makeController(repo: Partial<UserRepo>) {
  let capturedPayload: Record<string, unknown> | null = null;
  const moduleRef = await Test.createTestingModule({
    controllers: [AuthController],
    providers: [
      {
        provide: JwtService,
        useValue: {
          signAsync: jest.fn(async (payload: Record<string, unknown>) => {
            capturedPayload = payload;
            return 'test-token';
          }),
        },
      },
      { provide: UserRepo, useValue: repo },
    ],
  }).compile();
  return { controller: moduleRef.get(AuthController), getPayload: () => capturedPayload };
}

describe('AuthController.login（p6.1）', () => {
  it('登录成功：签 JWT 且 sub=employee_id（工号），返回用户信息', async () => {
    const { controller, getPayload } = await makeController({
      findByUsername: jest.fn(async () => DEV_ROW),
    });
    const res = await controller.login({ username: 'dev', password: 'Office@2026' });
    expect(res.access_token).toBe('test-token');
    expect(res.user).toEqual({ employee_id: 'EMP001', username: 'dev', role: 'admin' });
    expect(getPayload()!['sub']).toBe('EMP001'); // §2.8：身份键=工号
    expect(getPayload()!['username']).toBe('dev');
  });

  it('用户不存在 → 401 BAD_CREDENTIALS（与密码错误同一错误，不泄露账号存在性）', async () => {
    const { controller } = await makeController({ findByUsername: jest.fn(async () => null) });
    await expect(controller.login({ username: 'ghost', password: 'x' })).rejects.toMatchObject({
      status: 401,
      response: { code: 'BAD_CREDENTIALS' },
    });
  });

  it('密码错误 → 401', async () => {
    const { controller } = await makeController({ findByUsername: jest.fn(async () => DEV_ROW) });
    await expect(controller.login({ username: 'dev', password: 'wrong' })).rejects.toMatchObject({
      status: 401,
      response: { code: 'BAD_CREDENTIALS' },
    });
  });

  it('用户源不可用 → 503 USER_SOURCE_UNAVAILABLE（如实，不伪装成凭据错误）', async () => {
    const { controller } = await makeController({
      findByUsername: jest.fn(async () => {
        throw new Error('db down');
      }),
    });
    await expect(controller.login({ username: 'dev', password: 'Office@2026' })).rejects.toMatchObject({
      status: 503,
      response: { code: 'USER_SOURCE_UNAVAILABLE' },
    });
  });

  it('me()：回显验签后的身份', async () => {
    const { controller } = await makeController({});
    expect(controller.me({ user: { userId: 'EMP001', username: 'dev', role: 'admin' } } as never))
      .toEqual({ employee_id: 'EMP001', username: 'dev', role: 'admin' });
  });
});
