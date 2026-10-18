import { loadGatewayConfig } from './configuration';

describe('loadGatewayConfig（fail-closed 配置）', () => {
  const OLD = process.env;
  beforeEach(() => {
    process.env = { ...OLD };
  });
  afterAll(() => {
    process.env = OLD;
  });

  it('生产缺 GATEWAY_JWT_SECRET 抛错', () => {
    process.env.NODE_ENV = 'production';
    delete process.env.GATEWAY_JWT_SECRET;
    expect(() => loadGatewayConfig()).toThrow(/GATEWAY_JWT_SECRET/);
  });

  it('生产缺 INTERNAL_SHARED_SECRET 抛错', () => {
    process.env.NODE_ENV = 'production';
    process.env.GATEWAY_JWT_SECRET = 'x';
    delete process.env.INTERNAL_SHARED_SECRET;
    expect(() => loadGatewayConfig()).toThrow(/INTERNAL_SHARED_SECRET/);
  });

  it('开发缺密钥不抛，JWT 随机生成、internalToken 为空', () => {
    process.env.NODE_ENV = 'development';
    delete process.env.GATEWAY_JWT_SECRET;
    delete process.env.INTERNAL_SHARED_SECRET;
    const c = loadGatewayConfig();
    expect(c.jwtSecret.length).toBeGreaterThan(0);
    expect(c.internalToken).toBe('');
  });

  it('解析 allowedOrigins / backendUrl / port', () => {
    process.env.NODE_ENV = 'development';
    process.env.GATEWAY_ALLOWED_ORIGINS = 'http://a.com, http://b.com';
    process.env.GATEWAY_BACKEND_URL = 'http://backend:8000';
    process.env.GATEWAY_PORT = '3100';
    const c = loadGatewayConfig();
    expect(c.allowedOrigins).toEqual(['http://a.com', 'http://b.com']);
    expect(c.backendUrl).toBe('http://backend:8000');
    expect(c.port).toBe(3100);
  });
});
