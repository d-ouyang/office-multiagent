/**
 * LLM 代理 e2e（v2.2.0-p1.4 / B1）——B1 冒烟清单的测试层（CI 里跑假上游）。
 *
 * 覆盖：
 *   · 服务间密钥缺失/错误 → 401（fail-closed）；
 *   · 未登记 model → 404 MODEL_NOT_ROUTE；
 *   · 非流式透传：body.model 替换为 provider 侧真实名、Authorization 换真实 key、
 *     上游响应原样返回；
 *   · 流式透传（SSE）：逐块 pipe 不缓冲、顺序一致；
 *   · BAD_JSON → 400；provider key 未配置 → 502 PROVIDER_NOT_READY。
 *
 * 真实供应商冒烟（真 key 直连 vs 网关对比）是部署前的手工步骤，见迭代文档。
 */
import { INestApplication } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { Test } from '@nestjs/testing';
import * as http from 'node:http';
import type { AddressInfo } from 'node:net';
import request from 'supertest';

import { gatewayConfig } from '../config/configuration';
import { LlmProxyModule } from './llm-proxy.module';
import { setLlmRouteForTests, type LlmRouteTable } from './llm-route-table';

const INTERNAL_TOKEN = 'it-test-secret';
const FAKE_KEY = 'sk-real-provider-key';

/** 起一个假 provider 上游：断言收到的请求，按脚本回响应（支持流式）。 */
function startFakeProvider(
  handler: (req: http.IncomingMessage, body: string, res: http.ServerResponse) => void,
): Promise<{ url: string; close: () => Promise<void>; seen: { auth: string[]; bodies: string[] } }> {
  const seen = { auth: [] as string[], bodies: [] as string[] };
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (c) => (body += c));
    req.on('end', () => {
      seen.auth.push(String(req.headers.authorization ?? ''));
      seen.bodies.push(body);
      handler(req, body, res);
    });
  });
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address() as AddressInfo;
      resolve({
        url: `http://127.0.0.1:${port}/v1`,
        close: () =>
          new Promise((r) => {
            // Node 20 起转发用 http 全局 Agent 默认 keepAlive，会有残留 keep-alive 连接
            // 让 server.close() 永远等不到回调——先强制断开全部连接再 close。
            server.closeAllConnections();
            server.close(() => r());
          }),
        seen,
      });
    });
  });
}

describe('LlmProxyController (e2e)', () => {
  let app: INestApplication;
  let fake: Awaited<ReturnType<typeof startFakeProvider>>;
  let table: LlmRouteTable;

  beforeAll(async () => {
    process.env.INTERNAL_SHARED_SECRET = INTERNAL_TOKEN;
    process.env.FAKE_PROVIDER_KEY = FAKE_KEY;

    const moduleRef = await Test.createTestingModule({
      imports: [
        ConfigModule.forRoot({ isGlobal: true, load: [gatewayConfig], envFilePath: [] }),
        LlmProxyModule,
      ],
    }).compile();
    app = moduleRef.createNestApplication();
    await app.init();
  });

  afterAll(async () => {
    await app?.close();
    delete process.env.INTERNAL_SHARED_SECRET;
    delete process.env.FAKE_PROVIDER_KEY;
  });

  beforeEach(async () => {
    fake = await startFakeProvider((req, _body, res) => {
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ id: 'up-1', choices: [{ message: { content: 'ok' } }], usage: { total_tokens: 9 } }));
    });
    table = {
      providers: new Map([
        ['fake', { name: 'fake', baseUrl: fake.url, apiKey: FAKE_KEY }],
        ['nokey', { name: 'nokey', baseUrl: fake.url, apiKey: '' }],
      ]),
      models: new Map([
        ['deepseek-chat', { model: 'deepseek-chat', provider: table_provider('fake') }],
        ['deepseek-ai/DeepSeek-V3', { model: 'deepseek-ai/DeepSeek-V3', provider: table_provider('fake') }],
        ['secret-model', { model: 'secret-model', provider: table_provider('nokey') }],
      ]),
    };
    setLlmRouteForTests(table);
  });

  afterEach(async () => {
    await fake?.close();
  });

  function table_provider(name: string) {
    // helper：从 map 里取 provider（beforeEach 里表尚未构建好，用惰性引用包装）
    return {
      get name() {
        return table.providers.get(name)!.name;
      },
      get baseUrl() {
        return table.providers.get(name)!.baseUrl;
      },
      get apiKey() {
        return table.providers.get(name)!.apiKey;
      },
    };
  }

  const auth = { authorization: `Bearer ${INTERNAL_TOKEN}` };

  it('缺服务间密钥 → 401', async () => {
    const res = await request(app.getHttpServer()).post('/llm/v1/chat/completions').send({ model: 'deepseek-chat' });
    expect(res.status).toBe(401);
    expect(res.body.error.code).toBe('UNAUTHORIZED');
  });

  it('密钥错误 → 401', async () => {
    const res = await request(app.getHttpServer())
      .post('/llm/v1/chat/completions')
      .set({ authorization: 'Bearer wrong' })
      .send({ model: 'deepseek-chat' });
    expect(res.status).toBe(401);
  });

  it('未登记 model → 404 MODEL_NOT_ROUTE（fail-closed 不猜默认）', async () => {
    const res = await request(app.getHttpServer())
      .post('/llm/v1/chat/completions')
      .set(auth)
      .send({ model: 'unknown-model', messages: [] });
    expect(res.status).toBe(404);
    expect(res.body.error.code).toBe('MODEL_NOT_ROUTE');
  });

  it('非流式透传：model/Authorization 替换，响应原样', async () => {
    const res = await request(app.getHttpServer())
      .post('/llm/v1/chat/completions')
      .set(auth)
      .send({ model: 'deepseek-ai/DeepSeek-V3', messages: [{ role: 'user', content: 'hi' }] });
    expect(res.status).toBe(200);
    expect(res.body.id).toBe('up-1');
    // 上游收到的是替换后的真实模型名 + 真实 key
    const upstreamBody = JSON.parse(fake.seen.bodies[0]);
    expect(upstreamBody.model).toBe('deepseek-ai/DeepSeek-V3');
    expect(fake.seen.auth[0]).toBe(`Bearer ${FAKE_KEY}`);
  });

  it('流式透传：SSE 逐块顺序到达，不缓冲', async () => {
    await fake.close();
    fake = await startFakeProvider((_req, _body, res) => {
      res.writeHead(200, { 'content-type': 'text/event-stream' });
      res.write('data: {"choices":[{"delta":{"content":"你"}}]}\n\n');
      setTimeout(() => {
        res.write('data: {"choices":[{"delta":{"content":"好"}}]}\n\n');
        res.write('data: [DONE]\n\n');
        res.end();
      }, 50);
    });
    table.providers.set('fake', { name: 'fake', baseUrl: fake.url, apiKey: FAKE_KEY });

    const chunks: string[] = [];
    const res = await request(app.getHttpServer())
      .post('/llm/v1/chat/completions')
      .set(auth)
      .send({ model: 'deepseek-chat', stream: true, messages: [] })
      .buffer()
      .parse((res, cb) => {
        // 流式解析：每收到一段就记录（若被网关缓冲，这里只会收到一次整块）
        const parts: Buffer[] = [];
        res.on('data', (c: Buffer) => {
          parts.push(c);
          chunks.push(c.toString('utf-8'));
        });
        res.on('end', () => cb(null, Buffer.concat(parts)));
      });
    expect(res.status).toBe(200);
    const all = chunks.join('');
    expect(all).toContain('你');
    expect(all).toContain('好');
    expect(all).toContain('[DONE]');
  });

  it('BAD_JSON → 400', async () => {
    const res = await request(app.getHttpServer())
      .post('/llm/v1/chat/completions')
      .set(auth)
      .set('content-type', 'application/json')
      .send('not-json{{{');
    expect(res.status).toBe(400);
  });

  it('provider key 未配置 → 502 PROVIDER_NOT_READY', async () => {
    const res = await request(app.getHttpServer())
      .post('/llm/v1/chat/completions')
      .set(auth)
      .send({ model: 'secret-model', messages: [] });
    expect(res.status).toBe(502);
    expect(res.body.error.code).toBe('PROVIDER_NOT_READY');
  });
});
