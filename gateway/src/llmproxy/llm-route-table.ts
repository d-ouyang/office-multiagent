/**
 * LLM 供应商路由表（v2.2.0-p1.4 / B1 · gateway 内置 LLM 代理）。
 *
 * 与 route-table.ts 同一套设计模式（纯函数 + ${ENV} 展开 + 带缓存加载器），
 * 但路由维度不同：代理路径路由按【路径前缀】匹配上游；LLM 代理按【请求体里的
 * model（真实 api_model 名）】匹配 provider——所以单独一张表，不复用 Upstream。
 *
 * 铁律：
 *  · 真实 key 只存在于网关进程 env（api_key_env 指向的变量），本表与响应永不回显；
 *  · 表结构与 backend/config/models.yaml 的 llm_providers 一一对应，漂移由
 *    对照测试抓出（loadModelsYamlProviders 只为测试辅助，不进运行时）；
 *  · 未登记的 model → fail-closed 404（MODEL_NOT_ROUTE），绝不猜默认 provider。
 */
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import yaml from 'js-yaml';

export interface LlmProvider {
  name: string;
  baseUrl: string;
  apiKey: string; // 运行时从 env 展开后的真实 key（仅网关内存持有）
}

export interface LlmModelRoute {
  model: string; // 转发到 provider 时 body.model 应替换成的真实模型名
  provider: LlmProvider;
}

export interface LlmRouteTable {
  providers: Map<string, LlmProvider>;
  models: Map<string, LlmModelRoute>;
}

/** 展开 ${VAR} / ${VAR:-默认}（与 route-table.expandEnv 同语义，独立实现避免跨模块耦合）。 */
function expandEnv(value: string): string {
  return value.replace(/\$\{([A-Z0-9_]+)(?::-([^}]*))?\}/gi, (_m, name: string, def?: string) => {
    const v = process.env[name];
    return v !== undefined && v !== '' ? v : def ?? '';
  });
}

/** 把 YAML 原始对象规整成路由表；key 缺失的 provider 记 warning 但保留条目（启动不炸，调用时 502 带原因）。 */
export function loadLlmRouteTable(raw: unknown): LlmRouteTable {
  const obj = (raw ?? {}) as {
    providers?: Record<string, { base_url?: string; api_key_env?: string }>;
    models?: Record<string, { provider?: string; model?: string }>;
  };
  const providers = new Map<string, LlmProvider>();
  for (const [name, p] of Object.entries(obj.providers ?? {})) {
    providers.set(name, {
      name,
      baseUrl: expandEnv(String(p.base_url ?? '')).replace(/\/+$/, ''),
      apiKey: expandEnv(`\${${String(p.api_key_env ?? '')}}`),
    });
  }
  const models = new Map<string, LlmModelRoute>();
  for (const [apiModel, m] of Object.entries(obj.models ?? {})) {
    const provider = providers.get(String(m.provider ?? ''));
    if (!provider) continue; // 表内漂移（models 引用不存在的 provider）直接丢弃
    models.set(apiModel, { model: String(m.model ?? apiModel), provider });
  }
  return { providers, models };
}

let cached: LlmRouteTable | null = null;

/** 读取 llm-providers.yaml（带缓存）。文件缺失 → 空表（fail-closed：全部 404）。 */
export function getLlmRoute(): LlmRouteTable {
  if (cached) return cached;
  const path = resolve(process.cwd(), 'config', 'llm-providers.yaml');
  if (!existsSync(path)) {
    cached = { providers: new Map(), models: new Map() };
    return cached;
  }
  const raw = yaml.load(readFileSync(path, 'utf-8'));
  cached = loadLlmRouteTable(raw);
  return cached;
}

/** 测试用：清缓存（下次 getLlmRoute 重新读文件）。 */
export function resetLlmRouteCache(): void {
  cached = null;
}

/** 仅测试注入：e2e 用假上游地址替换真表，不落盘临时 yaml。生产代码不得调用。 */
export function setLlmRouteForTests(table: LlmRouteTable): void {
  cached = table;
}
