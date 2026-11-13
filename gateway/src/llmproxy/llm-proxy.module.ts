import { Module } from '@nestjs/common';

import { LlmProxyController } from './llm-proxy.controller';

/**
 * LLM 代理模块（v2.2.0-p1.4 / B1）。
 *
 * 注册顺序关键：必须放在 ProxyModule **之前**——Nest 按 imports 顺序注册路由，
 * 本模块的精确路由 `/llm/v1/chat/completions` 要先于代理通配 `'*'`（app.module
 * 里的顺序注释即此纪律）。
 */
@Module({
  controllers: [LlmProxyController],
})
export class LlmProxyModule {}
