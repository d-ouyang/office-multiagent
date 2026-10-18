/**
 * 全局 JWT 守卫（p2.1a）——对应 RAG gateway/src/auth/guards/jwt-auth.guard.ts。
 * 默认保护一切路由，@Public() 白名单放行；缺 token / 过期 / 无效一律 401（fail-closed）。
 */
import { CanActivate, ExecutionContext, Injectable, UnauthorizedException } from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { AuthGuard } from '@nestjs/passport';

import { IS_PUBLIC_KEY } from '../decorators/public.decorator';

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
