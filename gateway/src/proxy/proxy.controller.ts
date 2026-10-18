/**
 * 反向代理（p2.1a）——网关最后一站：把通过鉴权的请求转给后端 FastAPI，NDJSON 流式透传。
 *
 * 三条来自 RAG 实战的硬纪律（照搬，勿改）：
 *  1) 代理注册成【Controller 通配路由】而非 app.use 中间件——Express 中间件跑在
 *     Nest 守卫之前，挂中间件层会「没带 token 也转发成功」而日志一切正常，极难发现。
 *     只有走到 handler 才转发，鉴权一定已过。
 *  2) NDJSON 不缓冲：`selfHandleResponse: false`（代理自己 pipe，边收边转）；
 *     转发请求带 `Accept-Encoding: identity`，少一层 gzip 缓冲。
 *  3) `fixRequestBody` 必须在所有 `setHeader` 之后——它会 end 掉 proxyReq、
 *     此后 setHeader 抛 ERR_HTTP_HEADERS_SENT 且无人 catch，一个 POST 就能打挂进程。
 *
 * 白名单路径（@Public，只读脚手架）必须【声明在通配路由之前】：Express 按注册顺序
 * 匹配，顺序反了白名单会被守卫拒成 401（fail-closed 但白名单静默失效）。
 */
import { All, Controller, Inject, Logger, Next, Req, Res } from '@nestjs/common';
import { NextFunction, Request, Response } from 'express';
import { createProxyMiddleware, fixRequestBody, RequestHandler } from 'http-proxy-middleware';

import { Public } from '../auth/decorators/public.decorator';
import { GatewayConfig, gatewayConfig } from '../config/configuration';

/** 免 token 透传的上游路径（只读脚手架；精确路径，不做前缀通配）。 */
export const PUBLIC_PROXY_PATHS = ['api/v1/health', 'api/v1/models', 'api/v1/demo/stream'] as const;

@Controller()
export class ProxyController {
  private readonly logger = new Logger('Proxy');
  private readonly proxy: RequestHandler;

  constructor(@Inject(gatewayConfig.KEY) private readonly config: GatewayConfig) {
    this.proxy = createProxyMiddleware({
      target: config.backendUrl,
      changeOrigin: true,
      ws: false,
      xfwd: true,
      timeout: config.proxyTimeoutMs,
      proxyTimeout: config.proxyTimeoutMs,
      // 保持默认「代理自己 pipe 响应」：流式不被缓冲的前提
      selfHandleResponse: false,
      on: {
        proxyReq: (proxyReq, req) => {
          const incoming = req as Request;
          try {
            // 不压缩：NDJSON 逐字输出最怕中间多一层 gzip 缓冲
            proxyReq.setHeader('Accept-Encoding', 'identity');
            // 重写请求体（会 end 掉 proxyReq，必须在所有 setHeader 之后）
            fixRequestBody(proxyReq, req as Request);
          } catch (e) {
            this.logger.error(
              `注入转发请求失败（本次继续，下游可能拿不到完整请求体）| path=${incoming.originalUrl} err=${(e as Error).message}`,
            );
          }
        },
        proxyRes: (proxyRes, req) => {
          const incoming = req as Request;
          const code = proxyRes.statusCode ?? 200;
          // 4xx/5xx warn；正常流式会有大量 200，只 warn/error 不刷 debug
          if (code >= 400) {
            this.logger.warn(`${incoming.method} ${incoming.originalUrl} -> ${code}`);
          }
        },
        error: (err, req, res) => {
          const incoming = req as Request;
          this.logger.error(
            `代理转发失败 | path=${incoming.originalUrl} target=${config.backendUrl} err=${err.message}`,
          );
          const r = res as Response;
          // 已开始发响应（流式吐了一半）改不了状态码，只能断开
          if (r.headersSent) {
            r.end();
            return;
          }
          const timedOut = /timeout/i.test(err.message);
          r.status(timedOut ? 504 : 502).json({
            error: {
              code: timedOut ? 'UPSTREAM_TIMEOUT' : 'UPSTREAM_UNAVAILABLE',
              message: timedOut ? '后端响应超时，请稍后重试' : '后端暂时不可用，请稍后重试',
              detail: err.message,
            },
          });
        },
      },
    });
    this.logger.log(`反向代理就绪 | /api/v1/* -> ${config.backendUrl}（超时 ${config.proxyTimeoutMs}ms）`);
  }

  /** 白名单路径（只读脚手架）免 token 透传。⚠️ 必须声明在通配路由之前。 */
  @Public()
  @All([...PUBLIC_PROXY_PATHS])
  handlePublic(@Req() req: Request, @Res() res: Response, @Next() next: NextFunction): void {
    this.proxy(req, res, next);
  }

  /** 通配路由：/api/v1/* 其余一切（需 token，由全局 JwtAuthGuard 把关）。 */
  @All('api/v1/*')
  handle(@Req() req: Request, @Res() res: Response, @Next() next: NextFunction): void {
    this.proxy(req, res, next);
  }
}
