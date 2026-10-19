/**
 * 路由表（p5.0 · 共享网关 Phase A/B）——配置驱动的多上游解析。
 *
 * 纯函数 + 一个带缓存的加载器：
 *  · loadRouteTable(raw)：把 YAML 对象规整成 Upstream[]（展开 ${ENV}）。
 *  · matchUpstream / stripPrefix / resolveRoute / isPublicPath：纯逻辑，可单测。
 *  · getUpstreams()：读 routes.yaml（带缓存），供守卫与代理共用同一份表。
 *
 * 设计要点：
 *  · 多上游按【最长前缀】匹配（office 前缀 '' 是兜底，rag 前缀 'rag' 更具体）。
 *  · 未匹配到路由 → isPublicPath 返回 false（fail-closed，交给守卫 401 / 代理 404）。
 */
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import yaml from 'js-yaml';

export interface RouteRule {
  path: string;
  public: boolean;
}
export interface Upstream {
  name: string;
  prefix: string;
  baseUrl: string;
  routes: RouteRule[];
  /** 信任边界：剥离客户端传入的身份头（防伪造，防"顺手 curl 一下"）。 */
  stripIdentity: boolean;
  /** 注入可信身份（来自网关验过的 JWT）+ 网关证明（X-Internal-Auth）。 */
  injectIdentity: boolean;
  /** 网关证明密钥（${ENV} 展开，须与上游后端配置的同名密钥同值）。空=不注入证明。 */
  internalSecret: string;
}
export interface ResolvedRoute {
  upstream: Upstream;
  rule: RouteRule;
  forwardPath: string;
}

/** 展开 ${VAR} / ${VAR:-默认}（空串视为未设，走默认）。 */
export function expandEnv(value: string): string {
  return value.replace(/\$\{([A-Z0-9_]+)(?::-([^}]*))?\}/gi, (_m, name: string, def?: string) => {
    const v = process.env[name];
    return v !== undefined && v !== '' ? v : def ?? '';
  });
}

/** 把 YAML 原始对象规整成 Upstream[]。 */
export function loadRouteTable(raw: unknown): Upstream[] {
  const list = (raw as { upstreams?: unknown[] })?.upstreams;
  if (!Array.isArray(list)) return [];
  return list.map((u) => {
    const up = u as Record<string, unknown>;
    const routes = Array.isArray(up.routes) ? up.routes : [];
    return {
      name: String(up.name ?? ''),
      prefix: String(up.prefix ?? '').replace(/^\/+|\/+$/g, ''),
      baseUrl: expandEnv(String(up.base_url ?? '')),
      routes: routes.map((r) => {
        const rule = r as Record<string, unknown>;
        return {
          path: String(rule.path ?? '').replace(/^\/+/, ''),
          public: Boolean(rule.public),
        };
      }),
      stripIdentity: Boolean(up.strip_identity),
      injectIdentity: Boolean(up.inject_identity),
      internalSecret: expandEnv(String(up.internal_secret ?? '')),
    };
  });
}

/** 最长前缀匹配上游；prefix '' 为兜底。无匹配返回 null。 */
export function matchUpstream(upstreams: Upstream[], reqPath: string): Upstream | null {
  let best: Upstream | null = null;
  let bestLen = -1;
  for (const u of upstreams) {
    const p = u.prefix;
    const matches = p === '' || reqPath === `/${p}` || reqPath.startsWith(`/${p}/`);
    if (matches && p.length > bestLen) {
      best = u;
      bestLen = p.length;
    }
  }
  return best;
}

/** 剥掉外部前缀，得到转发给上游的 path（不带前导 /）。 */
export function stripPrefix(u: Upstream, reqPath: string): string {
  if (u.prefix === '') return reqPath.replace(/^\/+/, '');
  const pre = `/${u.prefix}`;
  const rest = reqPath.startsWith(pre) ? reqPath.slice(pre.length) : reqPath;
  return rest.replace(/^\/+/, '');
}

/** 在某个上游的 routes 里按最长前缀匹配。 */
export function matchRule(rules: RouteRule[], forwardPath: string): RouteRule | null {
  let best: RouteRule | null = null;
  let bestLen = -1;
  for (const r of rules) {
    if (forwardPath === r.path || forwardPath.startsWith(`${r.path}/`)) {
      if (r.path.length > bestLen) {
        best = r;
        bestLen = r.path.length;
      }
    }
  }
  return best;
}

export function resolveRoute(upstreams: Upstream[], reqPath: string): ResolvedRoute | null {
  const upstream = matchUpstream(upstreams, reqPath);
  if (!upstream) return null;
  const forwardPath = stripPrefix(upstream, reqPath);
  const rule = matchRule(upstream.routes, forwardPath);
  if (!rule) return null;
  return { upstream, rule, forwardPath };
}

/** 是否免 token：命中且 public。未命中 → false（fail-closed）。 */
export function isPublicPath(upstreams: Upstream[], reqPath: string): boolean {
  const r = resolveRoute(upstreams, reqPath);
  return r ? r.rule.public : false;
}

function resolveRoutesPath(): string {
  const candidates = [
    process.env.GATEWAY_ROUTES_CONFIG,
    resolve(process.cwd(), 'config/routes.yaml'),
    resolve(process.cwd(), '../config/routes.yaml'),
  ].filter(Boolean) as string[];
  for (const c of candidates) {
    if (existsSync(c)) return c;
  }
  throw new Error('routes.yaml 未找到；设 GATEWAY_ROUTES_CONFIG 或放到 gateway/config/routes.yaml');
}

let cache: Upstream[] | null = null;

/** 读 routes.yaml（带缓存）；测试可传 raw 走 loadRouteTable。 */
export function getUpstreams(): Upstream[] {
  if (cache) return cache;
  const raw = yaml.load(readFileSync(resolveRoutesPath(), 'utf-8'));
  cache = loadRouteTable(raw);
  return cache;
}

/** 测试用：清缓存。 */
export function _resetRouteTableCache(): void {
  cache = null;
}
