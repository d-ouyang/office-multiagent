/**
 * 全局 JWT 守卫（p2.1a → p5.0）——默认保护一切；放行条件二选一：
 *   ① @Public() 元数据（网关自身路由，如 /api/health、/api/internal/ping）；
 *   ② 路由表命中且 public（代理路径，见 config/routes.yaml）。
 * 缺 token / 过期 / 无效一律 401（fail-closed）。未命中路由 → 非公开 → 交给守卫 401。
 */
import { CanActivate, ExecutionContext, Injectable, UnauthorizedException } from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { AuthGuard } from '@nestjs/passport';
import type { Request } from 'express';

import { IS_PUBLIC_KEY } from '../decorators/public.decorator';
import { getUpstreams, isPublicPath } from '../../proxy/route-table';

@Injectable()
export class JwtAuthGuard extends AuthGuard('jwt') implements CanActivate {
  constructor(private readonly reflector: Reflector) {
    super();
  }

  canActivate(context: ExecutionContext) {
    const isPublic = this.reflector.getAllAndOverride<boolean>(IS_PUBLIC_KEY, [
      context.getHandler(),
      context.getClass(),
    ]);
    if (isPublic) return true;

    const req = context.switchToHttp().getRequest<Request>();
    if (isPublicPath(getUpstreams(), req.path)) return true;

    return super.canActivate(context);
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  handleRequest(err: any, user: any, info: any) {
    if (info && info.name === 'TokenExpiredError') {
      throw new UnauthorizedException({ code: 'TOKEN_EXPIRED', message: '登录已过期，请重新登录' });
    }
    if (err || !user) {
      throw new UnauthorizedException({ code: 'UNAUTHORIZED', message: '未登录或登录态无效' });
    }
    return user;
  }
}
