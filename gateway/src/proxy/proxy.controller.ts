/**
 * 反向代理（p2.1a → p5.0 共享网关）——网关最后一站：把通过鉴权的请求按【路由表】转给对应上游，NDJSON 流式透传。
 *
 * 来自 RAG 实战的硬纪律（照搬，勿改）：
 *  1) 代理注册成【Controller 通配路由】而非 app.use 中间件——Express 中间件跑在 Nest 守卫之前，
 *     挂中间件层会「没带 token 也转发成功」而日志一切正常。只有走到 handler 才转发，鉴权一定已过。
 *  2) NDJSON 不缓冲：`selfHandleResponse: false`；转发请求带 `Accept-Encoding: identity`。
 *  3) `fixRequestBody` 必须在所有 setHeader 之后——它会 end 掉 proxyReq，此后 setHeader 抛错无人 catch。
 *
 * p5.0 变化（共享网关 Phase A/B）：
 *  · 目标上游不再硬编码单个 backendUrl，而是按 config/routes.yaml 路由表解析（多上游）。
 *  · 公开/受保护由路由表的 public 决定（守卫 consult 同一张表），不再用 @Public 逐条声明。
 *  · 支持外部前缀剥离（如 /rag/* → 上游 /api/v1/*）。
 *  · Phase C：透传 correlation-id（X-Request-Id）到上游。
 */
import { All, Controller, Inject, Logger, Next, Req, Res } from '@nestjs/common';
import { NextFunction, Request, Response } from 'express';
import { createProxyMiddleware, fixRequestBody, RequestHandler } from 'http-proxy-middleware';

import { GatewayConfig, gatewayConfig } from '../config/configuration';
import type { AuthenticatedUser } from '../auth/strategies/jwt.strategy';
import { getUpstreams, resolveRoute, type Upstream } from './route-table';

/**
 * 客户端身份头清单 —— 与 RAG 后端 `core/identity.py` 的 `IDENTITY_HEADERS` 一一对应
 * （RAG 网关侧同名单在 `identity-headers.ts`）。转发前一律剥离：客户端伪造的身份头
 * 不许过网关；上游只信网关注入的（配合 X-Internal-Auth 网关证明）。
 */
export const INBOUND_IDENTITY_HEADERS = [
  'x-user-id',
  'x-username',
  'x-user-role',
  'x-role',
  'x-dept-id',
  'x-token-version',
  'x-user-kb-role',
  'x-identity-source',
  'x-internal-auth',
] as const;

@Controller()
export class ProxyController {
  private readonly logger = new Logger('Proxy');
  private readonly upstreams = getUpstreams();
  private readonly proxies = new Map<string, RequestHandler>();

  constructor(@Inject(gatewayConfig.KEY) private readonly config: GatewayConfig) {}

  /** 每个上游一个代理实例（target 不同），懒建 + 缓存。 */
  private getProxy(u: Upstream): RequestHandler {
    const existing = this.proxies.get(u.name);
    if (existing) return existing;
    const timeout = this.config.proxyTimeoutMs;
    const proxy = createProxyMiddleware({
      target: u.baseUrl,
      changeOrigin: true,
      ws: false,
      xfwd: true,
      timeout,
      proxyTimeout: timeout,
      // 保持默认「代理自己 pipe 响应」：流式不被缓冲的前提
      selfHandleResponse: false,
      on: {
        proxyReq: (proxyReq, req) => {
          const incoming = req as Request;
          try {
            // 不压缩：NDJSON 逐字输出最怕中间多一层 gzip 缓冲
            proxyReq.setHeader('Accept-Encoding', 'identity');
            // Phase C：透传 correlation-id 到上游（与后端 correlation_id 对齐）
            const rid = incoming.headers['x-request-id'];
            if (typeof rid === 'string' && rid) proxyReq.setHeader('X-Request-Id', rid);
            // 信任边界①：剥离客户端传入的身份头（防伪造）——上游只信网关注入的
            if (u.stripIdentity) {
              for (const h of INBOUND_IDENTITY_HEADERS) proxyReq.removeHeader(h);
            }
            // 信任边界②：注入网关验过的可信身份 + 网关证明（上游凭证明才认）
            // ⚠️ 刻意不注入 X-User-Id：两套系统的 user.id 是两个命名空间，注入数字 id
            //    可能在上游库里撞到另一个人的行；只注 X-Username，由上游按用户名回落
            //    解析（对齐 = 两边用户名一致，见《共享网关迁移设计》）。
            if (u.injectIdentity && u.internalSecret) {
              const user = (incoming as Request & { user?: AuthenticatedUser }).user;
              if (user?.username) {
                proxyReq.setHeader('X-Username', encodeURIComponent(String(user.username)));
                proxyReq.setHeader('X-Internal-Auth', u.internalSecret);
              }
            }
            // 重写请求体（会 end 掉 proxyReq，必须在所有 setHeader/removeHeader 之后）
            fixRequestBody(proxyReq, incoming);
          } catch (e) {
            this.logger.error(
              `注入转发请求失败（本次继续，下游可能拿不到完整请求体）| upstream=${u.name} path=${incoming.originalUrl} err=${(e as Error).message}`,
            );
          }
        },
        proxyRes: (proxyRes, req) => {
          const incoming = req as Request;
          const code = proxyRes.statusCode ?? 200;
          if (code >= 400) {
            this.logger.warn(`${incoming.method} ${incoming.originalUrl} -> ${code} [${u.name}]`);
          }
        },
        error: (err, req, res) => {
          const incoming = req as Request;
          this.logger.error(
            `代理转发失败 | path=${incoming.originalUrl} upstream=${u.name}(${u.baseUrl}) err=${err.message}`,
          );
          const r = res as Response;
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
    this.proxies.set(u.name, proxy);
    this.logger.log(`上游就绪 | [${u.name}] prefix=/${u.prefix || '(root)'} -> ${u.baseUrl}`);
    return proxy;
  }

  /** 通配路由：按路由表解析上游并转发（守卫已按同一张表判过公开/受保护）。 */
  @All('*')
  handle(@Req() req: Request, @Res() res: Response, @Next() next: NextFunction): void {
    const resolved = resolveRoute(this.upstreams, req.path);
    if (!resolved) {
      (res as Response).status(404).json({ error: { code: 'NO_ROUTE', message: '无匹配路由' } });
      return;
    }
    // 剥前缀：把 req.url 改成「转发路径 + 原 query」，代理据此拼上游 URL
    const qi = req.url.indexOf('?');
    const query = qi >= 0 ? req.url.slice(qi) : '';
    req.url = `/${resolved.forwardPath}${query}`;
    this.getProxy(resolved.upstream)(req, res, next);
  }
}
