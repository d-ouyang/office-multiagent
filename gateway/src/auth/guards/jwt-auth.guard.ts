/**
 * 全局 JWT 守卫（p2.1a → p5.0 → p7.1）——默认保护一切；放行条件二选一：
 *   ① @Public() 元数据（网关自身路由，如 /api/health、/api/internal/ping）；
 *   ② 路由表命中且 public（代理路径，见 config/routes.yaml）。
 * 缺 token / 过期 / 无效一律 401（fail-closed）。未命中路由 → 非公开 → 交给守卫 401。
 *
 * p7.1：管理端路径（/api/v1/admin/*）在验签通过后再查角色——非 admin/superadmin 403。
 * 这是第一道闸，后端仍会按自己的 user 表再校验一次（双保险，别只依赖一层）。
 */
import {
  CanActivate,
  ExecutionContext,
  ForbiddenException,
  Injectable,
  UnauthorizedException,
} from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { AuthGuard } from '@nestjs/passport';
import type { Request } from 'express';

import { IS_PUBLIC_KEY } from '../decorators/public.decorator';
import { getUpstreams, isPublicPath } from '../../proxy/route-table';

/** 管理端前缀（后端 /api/v1/admin/*） */
export const ADMIN_PATH_PREFIX = '/api/v1/admin';
const ADMIN_ROLES = new Set(['admin', 'superadmin']);

/** 该路径是否属于管理端（供守卫与测试共用；纯函数） */
export function isAdminPath(path: string | undefined): boolean {
  const p = path ?? '';
  return p === ADMIN_PATH_PREFIX || p.startsWith(`${ADMIN_PATH_PREFIX}/`);
}

/** 角色是否够管理员（纯函数；无角色一律不够） */
export function hasAdminRole(role: unknown): boolean {
  return typeof role === 'string' && ADMIN_ROLES.has(role);
}

@Injectable()
export class JwtAuthGuard extends AuthGuard('jwt') implements CanActivate {
  constructor(private readonly reflector: Reflector) {
    super();
  }

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const isPublic = this.reflector.getAllAndOverride<boolean>(IS_PUBLIC_KEY, [
      context.getHandler(),
      context.getClass(),
    ]);
    if (isPublic) return true;

    const req = context.switchToHttp().getRequest<Request>();
    if (isPublicPath(getUpstreams(), req.path)) return true;

    const ok = (await super.canActivate(context)) as boolean;
    if (isAdminPath(req.path)) {
      const user = req.user as { role?: string } | undefined;
      if (!user || !hasAdminRole(user.role)) {
        throw new ForbiddenException({ code: 'FORBIDDEN', message: '需要管理员权限' });
      }
    }
    return ok;
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
