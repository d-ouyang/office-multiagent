/**
 * 代理 e2e（p2.1a → p5.0 共享网关）：起假后端流式吐 NDJSON，验证网关
 *   · 白名单路径（demo/stream）免 token 且 NDJSON 逐行透传、不重排、不缓冲；
 *   · 其余 /api/v1/* 无 token → 401（fail-closed）；
 *   · 带有效 JWT → 放行并转发；
 *   · 多上游：/rag/* 路由到 rag 上游并剥前缀（p5.0 Phase B）；
 *   · 未命中路由 → 404 NO_ROUTE（fail-closed）；
 *   · correlation-id 透传到上游（Phase C）；
 *   · /api/internal/ping 走 node:http + X-Internal-Token 打通后端内部探活。
 */
import { INestApplication } from '@nestjs/common';
import { JwtService } from '@nestjs/jwt';
import { Test } from '@nestjs/testing';
import * as http from 'node:http';
import type { AddressInfo } from 'node:net';
import request from 'supertest';

import { AppModule } from '../app.module';

const JWT_SECRET = 'test-secret';
const INTERNAL_SECRET = 'internal-secret';

describe('Proxy e2e（NDJSON 透传 + 鉴权 + 多上游）', () => {
  let app: INestApplication;
  let backend: http.Server;
  let ragBackend: http.Server;
  let ragReceivedRid: string | undefined;

  beforeAll(async () => {
    process.env.NODE_ENV = 'development';
    process.env.GATEWAY_JWT_SECRET = JWT_SECRET;
    process.env.INTERNAL_SHARED_SECRET = INTERNAL_SECRET;
    process.env.GATEWAY_RATE_LIMIT_MAX = '0'; // 关限流，避免干扰计数断言
    process.env.RAG_INTERNAL_SECRET = 'rag-office-secret';

    backend = http.createServer((req, res) => {
      const url = req.url ?? '';
      if (url.startsWith('/api/v1/demo/stream')) {
        res.writeHead(200, { 'Content-Type': 'application/x-ndjson' });
        const lines = [
          { type: 'thinking_delta', run_id: 'r', turn_id: 't', seq: 1, data: { delta: 'a' } },
          { type: 'tool_call_start', run_id: 'r', turn_id: 't', seq: 2, data: { tool_id: 'x', name: 'web_search' } },
          { type: 'done', run_id: 'r', turn_id: 't', seq: 3, data: { status: 'done' } },
        ];
        let i = 0;
        const tick = () => {
          if (i < lines.length) {
            res.write(JSON.stringify(lines[i]) + '\n');
            i += 1;
            setTimeout(tick, 5);
          } else {
            res.end();
          }
        };
        tick();
        return;
      }
      if (url.startsWith('/api/v1/models')) {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ models: [{ id: 'deepseek-chat' }] }));
        return;
      }
      if (url.startsWith('/api/v1/internal/auth/ping')) {
        if (req.headers['x-internal-token'] === INTERNAL_SECRET) {
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ ok: true, source: 'config' }));
        } else {
          res.writeHead(401);
          res.end();
        }
        return;
      }
      if (url.startsWith('/api/v1/tasks')) {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ secret: true }));
        return;
      }
      res.writeHead(404);
      res.end();
    });
    await new Promise<void>((resolve) => backend.listen(0, '127.0.0.1', resolve));
    process.env.GATEWAY_BACKEND_URL = `http://127.0.0.1:${(backend.address() as AddressInfo).port}`;

    // rag 上游：剥前缀后应收到 /api/v1/qa；顺便记录收到的 correlation-id 与身份头
    ragBackend = http.createServer((req, res) => {
      ragReceivedRid = req.headers['x-request-id'] as string | undefined;
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(
        JSON.stringify({
          rag: true,
          path: req.url,
          username: req.headers['x-username'] ?? null,
          internalAuth: req.headers['x-internal-auth'] ?? null,
          userId: req.headers['x-user-id'] ?? null,
        }),
      );
    });
    await new Promise<void>((resolve) => ragBackend.listen(0, '127.0.0.1', resolve));
    process.env.RAG_BACKEND_URL = `http://127.0.0.1:${(ragBackend.address() as AddressInfo).port}`;

    const moduleRef = await Test.createTestingModule({ imports: [AppModule] }).compile();
    app = moduleRef.createNestApplication();
    await app.init();
  });

  afterAll(async () => {
    await app?.close();
    await new Promise<void>((resolve) => backend.close(() => resolve()));
    await new Promise<void>((resolve) => ragBackend.close(() => resolve()));
  });

  const token = () => new JwtService({ secret: JWT_SECRET }).sign({ sub: 1, username: 'u', role: 'user' });

  it('白名单 /api/v1/demo/stream 免 token，NDJSON 逐行透传且有序', async () => {
    const res = await request(app.getHttpServer()).get('/api/v1/demo/stream');
    expect(res.status).toBe(200);
    expect(res.headers['content-type']).toContain('ndjson');
    const events = res.text.split('\n').filter((l) => l.trim()).map((l) => JSON.parse(l));
    expect(events.map((e) => e.type)).toEqual(['thinking_delta', 'tool_call_start', 'done']);
    expect(events.map((e) => e.seq)).toEqual([1, 2, 3]);
  });

  it('白名单 /api/v1/models 透传 JSON', async () => {
    const res = await request(app.getHttpServer()).get('/api/v1/models');
    expect(res.status).toBe(200);
    expect(res.body.models[0].id).toBe('deepseek-chat');
  });

  it('非白名单 /api/v1/tasks 无 token → 401（fail-closed）', async () => {
    await request(app.getHttpServer()).get('/api/v1/tasks').expect(401);
  });

  it('带有效 JWT → 放行并转发', async () => {
    const res = await request(app.getHttpServer())
      .get('/api/v1/tasks')
      .set('Authorization', `Bearer ${token()}`);
    expect(res.status).toBe(200);
    expect(res.body.secret).toBe(true);
  });

  it('多上游：/rag/api/v1/qa 无 token → 401', async () => {
    await request(app.getHttpServer()).get('/rag/api/v1/qa').expect(401);
  });

  it('多上游：/rag 剥前缀 + 注入可信身份 + 剥伪造身份头 + correlation-id', async () => {
    const res = await request(app.getHttpServer())
      .get('/rag/api/v1/qa?x=1')
      .set('Authorization', `Bearer ${token()}`)
      .set('X-User-Id', '999'); // 客户端伪造的身份头
    expect(res.status).toBe(200);
    expect(res.body.rag).toBe(true);
    expect(res.body.path).toBe('/api/v1/qa?x=1'); // 剥掉 /rag，保留 query
    expect(res.body.username).toBe('u'); // 注入网关验过的身份（来自 JWT）
    expect(res.body.internalAuth).toBe('rag-office-secret'); // 网关证明
    expect(res.body.userId).toBeNull(); // 伪造头被剥离，且刻意不注入 X-User-Id
    expect(res.headers['x-request-id']).toBeTruthy();
    expect(ragReceivedRid).toBe(res.headers['x-request-id']); // 上游收到同一 correlation-id
  });

  it('未命中路由 → 404 NO_ROUTE（带 token）', async () => {
    const res = await request(app.getHttpServer())
      .get('/nope')
      .set('Authorization', `Bearer ${token()}`);
    expect(res.status).toBe(404);
    expect(res.body.error.code).toBe('NO_ROUTE');
  });

  it('/api/internal/ping 走 node:http + X-Internal-Token 打通后端', async () => {
    const res = await request(app.getHttpServer()).get('/api/internal/ping');
    expect(res.status).toBe(200);
    expect(res.body.ok).toBe(true);
  });
});
