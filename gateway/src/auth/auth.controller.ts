/**
 * 登录端点（p6.1）——认证单点在网关（§13.3）。
 *
 * POST /api/v1/auth/login（公开，路由表白名单）：username+password → bcrypt 校验 →
 *   签 JWT { sub: employee_id, username, role, uid }（§2.8 身份键=工号）。
 * GET  /api/v1/auth/me（受保护）：guard 验签后的 req.user 直接回显。
 *
 * 纪律：用户不存在与密码错误返回**同一个** BAD_CREDENTIALS（不泄露账号是否存在）；
 * MySQL 不可用如实 503（部署错误不伪装成凭据错误）。
 */
import { Body, Controller, Get, HttpException, HttpStatus, Post, Req } from '@nestjs/common';
import { JwtService } from '@nestjs/jwt';
import type { Request } from 'express';
import * as bcrypt from 'bcryptjs';
import { IsString, MinLength } from 'class-validator';

import { Public } from './decorators/public.decorator';
import { UserRepo } from './user-repo';

export class LoginDto {
  @IsString()
  @MinLength(1)
  username!: string;

  @IsString()
  @MinLength(1)
  password!: string;
}

const BAD_CREDENTIALS = { code: 'BAD_CREDENTIALS', message: '用户名或密码错误' };

@Controller()
export class AuthController {
  constructor(
    private readonly jwt: JwtService,
    private readonly repo: UserRepo,
  ) {}

  @Public()
  @Post('api/v1/auth/login')
  async login(@Body() dto: LoginDto): Promise<{ access_token: string; user: Record<string, string> }> {
    let user;
    try {
      user = await this.repo.findByUsername(dto.username);
    } catch {
      throw new HttpException(
        { code: 'USER_SOURCE_UNAVAILABLE', message: '用户数据暂时不可用，请稍后再试' },
        HttpStatus.SERVICE_UNAVAILABLE,
      );
    }
    if (!user) throw new HttpException(BAD_CREDENTIALS, HttpStatus.UNAUTHORIZED);
    const ok = await bcrypt.compare(dto.password, user.password_hash);
    if (!ok) throw new HttpException(BAD_CREDENTIALS, HttpStatus.UNAUTHORIZED);

    const access_token = await this.jwt.signAsync({
      sub: user.employee_id, // §2.8：身份键=工号，永不复用
      username: user.username,
      role: user.role,
      uid: user.id,
    });
    return {
      access_token,
      user: { employee_id: user.employee_id, username: user.username, role: user.role },
    };
  }

  /** 受保护（走全局 guard）：验过的 token 回显身份。 */
  @Get('api/v1/auth/me')
  me(@Req() req: Request): Record<string, string> {
    const u = req.user as { userId?: string; username?: string; role?: string };
    return { employee_id: String(u?.userId ?? ''), username: String(u?.username ?? ''), role: String(u?.role ?? '') };
  }
}
