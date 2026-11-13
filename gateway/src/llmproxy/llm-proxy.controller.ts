/**
 * LLM 代理（v2.2.0-p1.4 / B1 · gateway 内置 LLM 代理）——模型调用的唯一收口点。
 *
 * 为什么不用 http-proxy-middleware：代理维度不同。业务代理按【路径前缀】选上游；
 * LLM 代理按【请求体里的 model】选 provider，且要改写 body.model 与 Authorization，
 * 用 node:http 手写转发（含流式 pipe）最直白，也绕开 middleware 的 body 干预时序坑。
 *
 * 纪律（照搬 proxy.controller 的实战教训）：
 *  1) 注册为精确路由 Controller（app.module 里放在 ProxyModule 之前）——通配 '*' 最后
 *     注册才不会抢路由；守卫对 /llm/v1 放行（routes.yaml public），本控制器自校验
 *     服务间密钥（Authorization: Bearer ${INTERNAL_SHARED_SECRET}，与 backend 调
 *     网关时 llm.py 发的 api_key 天然同源——models.yaml 的 api_key_env 即它）。
 *  2) 流式不缓冲：上游响应直接 pipe 到 res，头只透传必要项（content-type / status）。
 *  3) 真实 key 只存在于网关内存（provider 表），任何错误路径都不回显。
 *  4) fail-closed：未登记 model → 404 MODEL_NOT_ROUTE；provider 未配 key → 502。
 *
 * Phase B2/B3 挂点：归因（X-Request-Id 已透传；tenant/user 从 backend 请求头拿）与
 * 预算短路（PolicyDecision）都在本控制器的转发前后落。
 */
import { All, Controller, Inject, Logger, Req, Res } from '@nestjs/common';
import type { Request as ExpressRequest, Response as ExpressResponse } from 'express';
import * as http from 'node:http';
import * as https from 'node:https';
import { URL } from 'node:url';

type ServerResponse = ExpressResponse;

import { GatewayConfig, gatewayConfig } from '../config/configuration';
import { getLlmRoute, type LlmModelRoute } from './llm-route-table';

const MAX_BODY_BYTES = 4 * 1024 * 1024; // 4MB：聊天请求（含长上下文）的合理上限

@Controller()
export class LlmProxyController {
  private readonly logger = new Logger('LlmProxy');

  constructor(@Inject(gatewayConfig.KEY) private readonly config: GatewayConfig) {}

  @All('llm/v1/chat/completions')
  async proxy(@Req() req: ExpressRequest, @Res() res: ServerResponse): Promise<void> {
    // 1) 服务间密钥校验（fail-closed）：backend 的 llm.py 会把 models.yaml 里
    //    api_key_env 指向的 INTERNAL_SHARED_SECRET 作为 Bearer 发来。
    const expected = this.config.internalToken;
    const auth = String(req.headers.authorization ?? '');
    if (auth !== `Bearer ${expected}`) {
      this.logger.warn('LLM 代理拒绝：服务间密钥缺失或不匹配');
      res.writeHead(401, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ error: { code: 'UNAUTHORIZED', message: '服务间密钥校验失败' } }));
      return;
    }

    // 2) 取请求体。⚠️ main.ts 已全局挂 express.json()——application/json 请求的
    //    流已被解析进 req.body，此刻再监听 data/end 永远等不到事件（请求挂死，
    //    实测 45s 超时）。所以优先读 req.body，仅对未解析的请求（理论上无）走流读取。
    let bodyText: string;
    if (req.body !== undefined) {
      bodyText = typeof req.body === 'string' ? req.body : JSON.stringify(req.body);
    } else {
      const streamed = await readBody(req, MAX_BODY_BYTES);
      if (streamed === null) {
        res.writeHead(413, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ error: { code: 'BODY_TOO_LARGE', message: `请求体超过 ${MAX_BODY_BYTES} 字节` } }));
        return;
      }
      bodyText = streamed;
    }
    let parsed: { model?: unknown };
    try {
      parsed = JSON.parse(bodyText || '{}');
    } catch {
      res.writeHead(400, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ error: { code: 'BAD_JSON', message: '请求体不是合法 JSON' } }));
      return;
    }
    const requestedModel = String(parsed.model ?? '');
    const route: LlmModelRoute | undefined = getLlmRoute().models.get(requestedModel);
    if (!route) {
      // fail-closed：不猜默认 provider，让"模型没登记"响亮失败
      this.logger.warn(`LLM 代理拒绝：模型未登记 model=${requestedModel}`);
      res.writeHead(404, { 'content-type': 'application/json' });
      res.end(
        JSON.stringify({ error: { code: 'MODEL_NOT_ROUTE', message: `模型未在网关路由表登记：${requestedModel}` } }),
      );
      return;
    }
    if (!route.provider.apiKey || !route.provider.baseUrl) {
      this.logger.error(`LLM 代理不可用：provider 缺 key 或 base_url provider=${route.provider.name}`);
      res.writeHead(502, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ error: { code: 'PROVIDER_NOT_READY', message: `供应商未就绪：${route.provider.name}` } }));
      return;
    }

    // 3) 改写并转发：model 换成 provider 侧真实名；key 换成真实密钥（内存中替换，不落日志）
    const upstreamBody: Record<string, unknown> = { ...parsed, model: route.model };
    const target = new URL(`${route.provider.baseUrl}/chat/completions`);
    const isStream = upstreamBody.stream === true;
    const headers: Record<string, string> = {
      'content-type': 'application/json',
      authorization: `Bearer ${route.provider.apiKey}`,
      accept: isStream ? 'text/event-stream' : 'application/json',
      // 透传 correlation-id（与业务代理同纪律），网关自身加一层来源标记
      'x-forwarded-by': 'office-gateway-llm-proxy',
    };
    const reqId = req.headers['x-request-id'];
    if (typeof reqId === 'string' && reqId) headers['x-request-id'] = reqId;

    this.logger.log(
      `LLM 代理转发 model=${requestedModel} -> ${route.provider.name}/${route.model} stream=${isStream}`,
    );

    // ⚠️ 按 provider 协议选 transport：真实 provider 全是 https，node:http 发不出
    // https 请求（会静默挂到客户端超时）——必须用 node:https。
    const transport = target.protocol === 'https:' ? https : http;
    const upstream = transport.request(
      {
        protocol: target.protocol,
        hostname: target.hostname,
        port: target.port || (target.protocol === 'https:' ? 443 : 80),
        path: target.pathname + target.search,
        method: 'POST',
        headers,
        timeout: this.config.proxyTimeoutMs,
      },
      (up) => {
        // 4) 响应透传：状态码 + content-type 原样，body 直接 pipe（流式零缓冲）
        res.writeHead(up.statusCode ?? 502, {
          'content-type': up.headers['content-type'] ?? 'application/json',
          'cache-control': 'no-store',
        });
        up.pipe(res);
        up.on('error', (err) => {
          this.logger.error(`上游响应错误 provider=${route.provider.name}: ${err.message}`);
          res.end();
        });
      },
    );
    upstream.on('timeout', () => {
      this.logger.error(`上游超时 provider=${route.provider.name} model=${route.model}`);
      upstream.destroy(new Error('upstream timeout'));
      if (!res.headersSent) {
        res.writeHead(504, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ error: { code: 'UPSTREAM_TIMEOUT', message: '供应商超时' } }));
      } else {
        res.end();
      }
    });
    upstream.on('error', (err) => {
      this.logger.error(`上游连接失败 provider=${route.provider.name}: ${err.message}`);
      if (!res.headersSent) {
        res.writeHead(502, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ error: { code: 'UPSTREAM_ERROR', message: `供应商连接失败：${err.message}` } }));
      } else {
        res.end();
      }
    });
    upstream.end(JSON.stringify(upstreamBody));
  }
}

/** 聚合请求体；超过上限返回 null（413）。仅用于「body parser 未消费流」的场景。 */
function readBody(req: ExpressRequest, max: number): Promise<string | null> {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks: Buffer[] = [];
    req.on('data', (c: Buffer) => {
      size += c.length;
      if (size > max) {
        reject(new Error('TOO_LARGE'));
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf-8')));
    req.on('error', reject);
  });
}
