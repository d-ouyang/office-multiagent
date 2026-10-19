/**
 * 网关配置（p2.1a）——精简版，保留 RAG 的关键纪律：配置只从环境变量读，
 * 关键项「生产缺失即启动失败」（fail-closed，不搞「能启动但没防护」）。
 *
 * 与后端的关系：
 *   · jwtSecret 必须与后端 JWT_SECRET 【同值】——用户 JWT 由网关签、后端 PyJWT 验（§13.3）。
 *   · internalToken 必须与后端 INTERNAL_SHARED_SECRET 【同值】——网关→后端内部调用信任密钥。
 */
import { registerAs } from '@nestjs/config';
import { Logger } from '@nestjs/common';
import { randomBytes } from 'node:crypto';

const logger = new Logger('GatewayConfig');

export interface GatewayConfig {
  port: number;
  jwtSecret: string;
  jwtExpiresIn: string;
  backendUrl: string;
  internalAuthPath: string;
  internalToken: string;
  allowedOrigins: string[];
  proxyTimeoutMs: number;
  rateLimitMax: number;        // 每 IP 每窗口最大请求数；0=关闭
  rateLimitWindowMs: number;   // 限流窗口（毫秒）
  isProduction: boolean;
}

function list(value: string | undefined, fallback: string[]): string[] {
  if (!value) return fallback;
  return value.split(',').map((v) => v.trim()).filter(Boolean);
}

/**
 * JWT 密钥：生产必须显式配置（与后端同值）；开发缺失时随机生成
 * （重启即失效、踢掉登录态，这个副作用本身就是提醒：去配一个固定密钥）。
 */
function loadJwtSecret(isProduction: boolean): string {
  const secret = process.env.GATEWAY_JWT_SECRET ?? '';
  if (secret) return secret;
  if (isProduction) {
    throw new Error(
      '生产环境必须配置 GATEWAY_JWT_SECRET（与后端 JWT_SECRET 同值；建议 openssl rand -hex 32 生成）',
    );
  }
  logger.warn('未配置 GATEWAY_JWT_SECRET，已生成临时随机密钥（本进程重启后所有登录态失效）');
  return randomBytes(32).toString('hex');
}

/** 内部共享密钥：生产缺失直接抛错（缺了它网关→后端内部调用全 401，排查要跨进程）。 */
function loadInternalToken(isProduction: boolean): string {
  const token = process.env.INTERNAL_SHARED_SECRET ?? '';
  if (!token && isProduction) {
    throw new Error('生产环境必须配置 INTERNAL_SHARED_SECRET（与后端同值）');
  }
  if (!token) {
    logger.warn('未配置 INTERNAL_SHARED_SECRET：网关→后端内部调用将不可用（开发环境预期行为）');
  }
  return token;
}

export function loadGatewayConfig(): GatewayConfig {
  const isProduction = (process.env.NODE_ENV ?? 'development') === 'production';
  return {
    port: Number(process.env.GATEWAY_PORT ?? 3000),
    jwtSecret: loadJwtSecret(isProduction),
    jwtExpiresIn: process.env.GATEWAY_JWT_EXPIRES_IN ?? '12h',
    // 容器里是 http://backend:8000；本机开发 http://127.0.0.1:8000（用 127.0.0.1 避 IPv6 ::1 坑）
    backendUrl: process.env.GATEWAY_BACKEND_URL ?? 'http://127.0.0.1:8000',
    internalAuthPath: process.env.GATEWAY_INTERNAL_AUTH_PATH ?? '/api/v1/internal/auth/ping',
    internalToken: loadInternalToken(isProduction),
    allowedOrigins: list(process.env.GATEWAY_ALLOWED_ORIGINS, [
      'http://localhost:5173',
      'http://127.0.0.1:5173',
      'http://localhost:8080',
    ]),
    proxyTimeoutMs: Number(process.env.GATEWAY_PROXY_TIMEOUT_MS ?? 180_000),
    // 内存固定窗口限流（每 IP）；多副本下是每实例计数，严格全局限流需 Redis（文档标注）
    rateLimitMax: Number(process.env.GATEWAY_RATE_LIMIT_MAX ?? 600),
    rateLimitWindowMs: Number(process.env.GATEWAY_RATE_LIMIT_WINDOW_MS ?? 60_000),
    isProduction,
  };
}

export const gatewayConfig = registerAs('gateway', loadGatewayConfig);
