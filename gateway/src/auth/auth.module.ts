import { Module } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { JwtModule } from '@nestjs/jwt';
import { PassportModule } from '@nestjs/passport';

import { gatewayConfig } from '../config/configuration';
import { AuthController } from './auth.controller';
import { JwtStrategy } from './strategies/jwt.strategy';
import { UserRepo } from './user-repo';

@Module({
  imports: [
    PassportModule,
    // 签发与验签同密钥（§13.3）：strategy 读 jwtSecret 验，这里注册给签发用
    JwtModule.registerAsync({
      inject: [gatewayConfig.KEY],
      useFactory: (cfg: ConfigType<typeof gatewayConfig>) => ({
        secret: cfg.jwtSecret,
        signOptions: { expiresIn: cfg.jwtExpiresIn },
      }),
    }),
  ],
  controllers: [AuthController],
  providers: [
    JwtStrategy,
    {
      provide: UserRepo,
      inject: [gatewayConfig.KEY],
      useFactory: (cfg: ConfigType<typeof gatewayConfig>) =>
        new UserRepo({
          host: cfg.mysqlHost,
          port: cfg.mysqlPort,
          user: cfg.mysqlUser,
          password: cfg.mysqlPassword,
          database: cfg.mysqlDatabase,
        }),
    },
  ],
})
export class AuthModule {}
