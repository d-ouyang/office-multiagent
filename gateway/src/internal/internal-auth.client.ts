/**
 * 内部调用客户端（p2.1a）——对应 RAG gateway/src/auth/internal-auth.client.ts。
 *
 * ⚠️ 用 `node:http` 而非全局 `fetch`：Node 的 fetch（undici）会读 HTTP_PROXY，
 * 而网关→后端是同 compose 网络内网调用，挂代理的机器上会被导到代理端口导致
 * ECONNREFUSED（症状是「后端没起」，其实后端活着）。node:http 不读代理环境变量。
 */
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import * as http from 'node:http';

import { GatewayConfig } from '../config/configuration';

export interface InternalPingResult {
  ok: boolean;
  detail: string;
}

@Injectable()
export class InternalAuthClient {
  private readonly logger = new Logger(InternalAuthClient.name);

  constructor(private readonly config: ConfigService) {}

  /** 调后端内部探活（带 X-Internal-Token）。区分「判定没跑成」与「跑完不通过」。 */
  async ping(): Promise<InternalPingResult> {
    const cfg = this.config.getOrThrow<GatewayConfig>('gateway');
    if (!cfg.internalToken) {
      return { ok: false, detail: 'INTERNAL_SHARED_SECRET 未配置（网关侧）' };
    }
    const target = new URL(cfg.internalAuthPath, cfg.backendUrl.replace(/\/+$/, ''));
    const body = await this.request(target, cfg.internalToken);
    if (body === null) {
      return { ok: false, detail: `后端不可达或未返回 200：${target.origin}${target.pathname}` };
    }
    return { ok: true, detail: body };
  }

  private request(target: URL, token: string): Promise<string | null> {
    return new Promise((resolve) => {
      const req = http.request(
        {
          hostname: target.hostname,
          port: target.port || 80,
          path: target.pathname,
          method: 'GET',
          headers: { 'X-Internal-Token': token },
          timeout: 5000,
        },
        (res) => {
          let raw = '';
          res.on('data', (c) => (raw += c));
          res.on('end', () => resolve(res.statusCode === 200 ? raw : null));
        },
      );
      req.on('timeout', () => {
        req.destroy();
        resolve(null);
      });
      req.on('error', (e) => {
        this.logger.warn(`内部调用失败 | ${(e as Error).message}`);
        resolve(null);
      });
      req.end();
    });
  }
}
