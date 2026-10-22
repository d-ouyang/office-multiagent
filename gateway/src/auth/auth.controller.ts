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

export class ChangePasswordDto {
  @IsString()
  @MinLength(1)
  old_password!: string;

  @IsString()
  @MinLength(1)
  new_password!: string;
}

const BAD_CREDENTIALS = { code: 'BAD_CREDENTIALS', message: '用户名或密码错误' };
const REVOKED = { code: 'TOKEN_REVOKED', message: '登录已失效，请重新登录' };

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

    const access_token = await this.sign(user);
    return {
      access_token,
      user: { employee_id: user.employee_id, username: user.username, role: user.role },
    };
  }

  /** 改密：校验旧密码，token_version +1，签发新 token。旧 token 立即失效。 */
  @Post('api/v1/auth/password')
  async changePassword(@Body() dto: ChangePasswordDto, @Req() req: Request): Promise<{ access_token: string }> {
    const auth = req.user as { userId?: string; tv?: number };
    const employeeId = String(auth?.userId ?? '');
    if (!employeeId) throw new HttpException(REVOKED, HttpStatus.UNAUTHORIZED);
    if (dto.new_password.length < 8) {
      throw new HttpException(
        { code: 'WEAK_PASSWORD', message: '新密码至少 8 位' },
        HttpStatus.BAD_REQUEST,
      );
    }
    let user;
    try {
      user = await this.repo.findByEmployeeId(employeeId);
    } catch {
      throw new HttpException(
        { code: 'USER_SOURCE_UNAVAILABLE', message: '用户数据暂时不可用，请稍后再试' },
        HttpStatus.SERVICE_UNAVAILABLE,
      );
    }
    if (!user) throw new HttpException(REVOKED, HttpStatus.UNAUTHORIZED);
    if (Number(user.token_version ?? 0) !== Number(auth.tv ?? 0)) {
      throw new HttpException(REVOKED, HttpStatus.UNAUTHORIZED);
    }
    const ok = await bcrypt.compare(dto.old_password, user.password_hash);
    if (!ok) {
      throw new HttpException({ code: 'BAD_PASSWORD', message: '当前密码不正确' }, HttpStatus.UNAUTHORIZED);
    }
    if (dto.new_password === dto.old_password) {
      throw new HttpException({ code: 'SAME_PASSWORD', message: '新密码不能与当前密码相同' }, HttpStatus.BAD_REQUEST);
    }
    const hash = await bcrypt.hash(dto.new_password, 12);
    let tv: number;
    try {
      tv = await this.repo.updatePassword(employeeId, hash);
    } catch {
      throw new HttpException(
        { code: 'USER_SOURCE_UNAVAILABLE', message: '用户数据暂时不可用，请稍后再试' },
        HttpStatus.SERVICE_UNAVAILABLE,
      );
    }
    user.token_version = tv;
    return { access_token: await this.sign(user) };
  }

  private sign(user: { employee_id: string; username: string; role: string; id: number; token_version?: number }) {
    return this.jwt.signAsync({
      sub: user.employee_id,
      username: user.username,
      role: user.role,
      uid: user.id,
      tv: Number(user.token_version ?? 0),
    });
  }

  /** 受保护（走全局 guard）：验过的 token 回显身份。 */
  @Get('api/v1/auth/me')
  me(@Req() req: Request): Record<string, string> {
    const u = req.user as { userId?: string; username?: string; role?: string };
    return { employee_id: String(u?.userId ?? ''), username: String(u?.username ?? ''), role: String(u?.role ?? '') };
  }
}
