/**
 * 限流中间件（p5.0 Phase C）——每 IP 固定窗口，超限 429（统一错误体）。
 * 内存计数（每实例）；GATEWAY_RATE_LIMIT_MAX=0 关闭。严格全局限流留待 Redis（文档标注）。
 */
import { Injectable, NestMiddleware } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { NextFunction, Request, Response } from 'express';

import { FixedWindowCounter } from '../rate-limiter';
import type { GatewayConfig } from '../../config/configuration';

@Injectable()
export class RateLimitMiddleware implements NestMiddleware {
  private readonly counter: FixedWindowCounter;

  constructor(private readonly config: ConfigService) {
    const c = this.config.getOrThrow<GatewayConfig>('gateway');
    this.counter = new FixedWindowCounter(c.rateLimitMax, c.rateLimitWindowMs);
  }

  use(req: Request, res: Response, next: NextFunction): void {
    const c = this.config.getOrThrow<GatewayConfig>('gateway');
    const requestId = (req.headers['x-request-id'] as string) || '-';
    if (c.rateLimitMax <= 0) return next();
    if (!this.counter.allow(req.ip || 'unknown', Date.now())) {
      res.status(429).json({
        error: { code: 'TOO_MANY_REQUESTS', message: '请求过于频繁，请稍后再试', requestId },
      });
      return;
    }
    next();
  }
}
