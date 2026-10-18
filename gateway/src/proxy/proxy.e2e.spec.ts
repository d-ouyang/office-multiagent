/**
 * 代理 e2e（p2.1a）：起一个假后端流式吐 NDJSON，验证网关
 *   · 白名单路径（demo/stream）免 token 且 NDJSON 逐行透传、不重排、不缓冲；
 *   · 其余 /api/v1/* 无 token → 401（fail-closed）；
 *   · 带有效 JWT → 放行并转发；
 *   · /api/internal/ping 走 node:http + X-Internal-Token 打通后端内部探活。
 */
import { INestApplication } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { JwtService } from '@nestjs/jwt';
import { Test } from '@nestjs/testing';
import * as http from 'node:http';
import type { AddressInfo } from 'node:net';
import request from 'supertest';

import { AppModule } from '../app.module';

const JWT_SECRET = 'test-secret';
const INTERNAL_SECRET = 'internal-secret';

describe('Proxy e2e（NDJSON 透传 + 鉴权）', () => {
  let app: INestApplication;
  let backend: http.Server;
  let backendUrl: string;

  beforeAll(async () => {
    // 在 AppModule 解析配置前设好环境变量（开发态，密钥显式给，确定可知）
    process.env.NODE_ENV = 'development';
    process.env.GATEWAY_JWT_SECRET = JWT_SECRET;
    process.env.INTERNAL_SHARED_SECRET = INTERNAL_SECRET;

    backend = http.createServer((req, res) => {
      const url = req.url ?? '';
      if (url.startsWith('/api/v1/demo/stream')) {
        res.writeHead(200, { 'Content-Type': 'application/x-ndjson' });
        // 逐行写、行间轻微延迟，模拟流式
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
    const port = (backend.address() as AddressInfo).port;
    backendUrl = `http://127.0.0.1:${port}`;
    process.env.GATEWAY_BACKEND_URL = backendUrl;

    const moduleRef = await Test.createTestingModule({ imports: [AppModule] }).compile();
    app = moduleRef.createNestApplication();
    await app.init();
  });

  afterAll(async () => {
    await app?.close();
    await new Promise<void>((resolve) => backend.close(() => resolve()));
  });

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
    const jwt = new JwtService({ secret: JWT_SECRET });
    const token = jwt.sign({ sub: 1, username: 'u', role: 'user' });
    const res = await request(app.getHttpServer())
      .get('/api/v1/tasks')
      .set('Authorization', `Bearer ${token}`);
    expect(res.status).toBe(200);
    expect(res.body.secret).toBe(true);
  });

  it('/api/internal/ping 走 node:http + X-Internal-Token 打通后端', async () => {
    const res = await request(app.getHttpServer()).get('/api/internal/ping');
    expect(res.status).toBe(200);
    expect(res.body.ok).toBe(true);
  });
});
