import {
  expandEnv,
  isPublicPath,
  loadRouteTable,
  matchUpstream,
  resolveRoute,
  stripPrefix,
  type Upstream,
} from './route-table';

const table: Upstream[] = loadRouteTable({
  upstreams: [
    {
      name: 'office',
      prefix: '',
      base_url: 'http://backend:8000',
      routes: [
        { path: 'api/v1/health', public: true },
        { path: 'api/v1/demo/stream', public: true },
        { path: 'api/v1', public: false },
      ],
    },
    {
      name: 'rag',
      prefix: 'rag',
      base_url: 'http://host.docker.internal:8000',
      routes: [
        { path: 'api/v1/system/health', public: true },
        { path: 'api/v1', public: false },
      ],
    },
  ],
});

describe('expandEnv', () => {
  const OLD = process.env.FOO;
  afterEach(() => {
    if (OLD === undefined) delete process.env.FOO;
    else process.env.FOO = OLD;
  });
  it('替换 ${VAR} 与 ${VAR:-默认}', () => {
    process.env.FOO = 'bar';
    expect(expandEnv('${FOO}')).toBe('bar');
    expect(expandEnv('${MISSING:-http://x}')).toBe('http://x');
    expect(expandEnv('a${FOO}b')).toBe('abarb');
  });
});

describe('matchUpstream 最长前缀', () => {
  it('office 兜底匹配 /api/v1/*', () => {
    expect(matchUpstream(table, '/api/v1/health')?.name).toBe('office');
  });
  it('/rag/* 命中 rag（比 office 兜底更具体）', () => {
    expect(matchUpstream(table, '/rag/api/v1/qa')?.name).toBe('rag');
  });
  it('/ragfoo 不命中 rag（边界，回落 office）', () => {
    expect(matchUpstream(table, '/ragfoo')?.name).toBe('office');
  });
});

describe('stripPrefix', () => {
  it('office 空前缀：仅去前导 /', () => {
    expect(stripPrefix(table[0], '/api/v1/health')).toBe('api/v1/health');
  });
  it('rag 剥成 /api/v1/*', () => {
    expect(stripPrefix(table[1], '/rag/api/v1/qa/ask')).toBe('api/v1/qa/ask');
  });
});

describe('resolveRoute + isPublicPath', () => {
  it('公开路径识别', () => {
    expect(isPublicPath(table, '/api/v1/health')).toBe(true);
    expect(isPublicPath(table, '/api/v1/demo/stream')).toBe(true);
    expect(isPublicPath(table, '/rag/api/v1/system/health')).toBe(true);
  });
  it('受保护路径', () => {
    expect(isPublicPath(table, '/api/v1/tasks')).toBe(false);
    expect(isPublicPath(table, '/rag/api/v1/qa')).toBe(false);
  });
  it('未命中路由 → fail-closed 非公开', () => {
    expect(isPublicPath(table, '/nope')).toBe(false);
    expect(resolveRoute(table, '/nope')).toBeNull();
  });
  it('rag 转发路径正确', () => {
    const r = resolveRoute(table, '/rag/api/v1/qa/ask');
    expect(r?.upstream.name).toBe('rag');
    expect(r?.forwardPath).toBe('api/v1/qa/ask');
    expect(r?.rule.public).toBe(false);
  });
});
