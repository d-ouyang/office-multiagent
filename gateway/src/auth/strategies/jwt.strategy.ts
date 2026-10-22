/**
 * JWT 策略（p2.1a）——对应 RAG gateway/src/auth/strategies/jwt.strategy.ts。
 *
 * 与后端 PyJWT 的分工：网关用 passport-jwt 【验签】用户 token，密钥 jwtSecret
 * 与后端 JWT_SECRET 同值（§13.3）。登录签发端点留到用户模型落地后再加；
 * 当前守卫先就位，敏感路径 fail-closed，只读脚手架路径（health/models/demo）放行。
 */
import { Inject, Injectable } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { PassportStrategy } from '@nestjs/passport';
import { ExtractJwt, Strategy } from 'passport-jwt';

import { gatewayConfig } from '../../config/configuration';

export interface AuthenticatedUser {
  userId: string | number;
  username: string;
  role: string;
  tv: number;
}

@Injectable()
export class JwtStrategy extends PassportStrategy(Strategy) {
  constructor(@Inject(gatewayConfig.KEY) config: ConfigType<typeof gatewayConfig>) {
    super({
      jwtFromRequest: ExtractJwt.fromAuthHeaderAsBearerToken(),
      ignoreExpiration: false,
      secretOrKey: config.jwtSecret,
    });
  }

  /**
   * fail-closed：payload 缺关键字段也返回一个「空身份」而不是抛错，
   * 由守卫据 user 是否有效决定放行与否（见 jwt-auth.guard.handleRequest）。
   */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  validate(payload: any): AuthenticatedUser {
    return {
      userId: payload.sub ?? payload.userId ?? '',
      username: payload.username ?? '',
      role: payload.role ?? 'user',
      tv: Number(payload.tv ?? 0),
    };
  }
}
