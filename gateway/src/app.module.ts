import { MiddlewareConsumer, Module, NestModule } from '@nestjs/common';
import { APP_GUARD } from '@nestjs/core';
import { ConfigModule } from '@nestjs/config';

import { AuthModule } from './auth/auth.module';
import { HealthModule } from './health/health.module';
import { InternalModule } from './internal/internal.module';
import { ProxyModule } from './proxy/proxy.module';
import { JwtAuthGuard } from './auth/guards/jwt-auth.guard';
import { RequestIdMiddleware } from './common/middlewares/request-id.middleware';
import { RateLimitMiddleware } from './common/middlewares/rate-limit.middleware';
import { gatewayConfig } from './config/configuration';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      load: [gatewayConfig],
      envFilePath: ['.env'],
    }),
    AuthModule,
    HealthModule,
    InternalModule,
    // 代理模块放最后：Nest 按 imports 顺序注册路由，通配路由最后注册才不会抢在前面。
    ProxyModule,
  ],
  providers: [
    // 全局守卫：默认保护一切，@Public()/路由表 public 放行（fail-closed）。
    { provide: APP_GUARD, useClass: JwtAuthGuard },
    RateLimitMiddleware,
  ],
})
export class AppModule implements NestModule {
  configure(consumer: MiddlewareConsumer): void {
    // 顺序：requestId 先（写 x-request-id）→ 限流（429 体能带上 requestId）。
    consumer.apply(RequestIdMiddleware, RateLimitMiddleware).forRoutes('*');
  }
}
