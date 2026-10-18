/**
 * 网关启动入口（p2.1a）。
 *
 * 三件事（照搬 RAG 经验）：
 *   ① 关掉 Nest 默认 body parser 再手动挂——让「请求体怎么解析」显式可控
 *      （默认 json limit 100kb 会让长文本提问吃 413；multipart 不被解析，流可 pipe）；
 *   ② CORS 必须在守卫之前生效——OPTIONS 预检不带 Authorization，被守卫拦会 401，
 *      表现为「前端怎么都登录不上，控制台只有一条 CORS 报错」；
 *   ③ 启动摘要只打印「有无配置」不打印值本身。
 */
import 'reflect-metadata';
import { Logger, ValidationPipe } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { NestFactory } from '@nestjs/core';
import { NestExpressApplication } from '@nestjs/platform-express';
import { json, urlencoded } from 'express';

import { AppModule } from './app.module';
import { GatewayConfig } from './config/configuration';

// 进程级异常兜底：网关是无状态转发服务，单请求异常不让进程退出（可用性优先）。
// 代价：若将来网关持有进程内状态（如内存限流计数），此兜底会「带损坏状态继续」，
// 那时应改为记录后退出、由编排层拉起。当前选择明确。
process.on('uncaughtException', (err) => {
  new Logger('Uncaught').error(`未捕获异常（进程继续运行）：${err.message}`);
});
process.on('unhandledRejection', (reason) => {
  const detail = reason instanceof Error ? reason.message : String(reason);
  new Logger('UnhandledRejection').error(`未处理的 Promise 拒绝（进程继续运行）：${detail}`);
});

async function bootstrap(): Promise<void> {
  const logger = new Logger('Bootstrap');

  const app = await NestFactory.create<NestExpressApplication>(AppModule, {
    bodyParser: false,
    logger: ['log', 'warn', 'error'],
  });

  const config = app.get(ConfigService).getOrThrow<GatewayConfig>('gateway');

  // ① 显式挂 body parser（原因见文件头）
  app.use(json({ limit: '4mb' }));
  app.use(urlencoded({ extended: true, limit: '4mb' }));

  // ② CORS（在守卫之前，保护 OPTIONS 预检）
  app.enableCors({
    origin: config.allowedOrigins,
    credentials: true,
    allowedHeaders: ['Content-Type', 'Authorization', 'X-Request-Id'],
    exposedHeaders: ['X-Request-Id'],
    maxAge: 600,
  });

  // trust proxy 是安全开关，仅当网关确实躲在会用 $remote_addr 覆盖 XFF 的反代之后才开。
  if (process.env.GATEWAY_TRUST_PROXY === 'true') {
    app.set('trust proxy', true);
    logger.log('已启用 trust proxy：req.ip 采信 X-Forwarded-For');
  }

  app.useGlobalPipes(new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true }));
  // SIGTERM 先停收新请求再退出（容器滚动更新不掐断在途请求）
  app.enableShutdownHooks();

  await app.listen(config.port, '0.0.0.0');

  logger.log(`网关已启动 | http://0.0.0.0:${config.port} env=${config.isProduction ? 'production' : 'development'}`);
  logger.log(`转发规则 | /api/v1/* -> ${config.backendUrl}（代理超时 ${config.proxyTimeoutMs}ms）`);
  logger.log(`CORS | 允许来源=${config.allowedOrigins.join(' ')}`);
}

bootstrap().catch((err) => {
  // 配置缺失（如生产没设密钥）走这里：打印人话后非 0 退出，让编排判定启动失败，
  // 而不是「起来了但没防护」。
  new Logger('Bootstrap').error(`网关启动失败：${err instanceof Error ? err.message : String(err)}`);
  process.exit(1);
});
