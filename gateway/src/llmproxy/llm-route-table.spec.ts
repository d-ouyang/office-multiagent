/**
 * LLM 供应商路由表单测（v2.2.0-p1.4 / B1）——纯函数，无网络。
 */
import { loadLlmRouteTable } from './llm-route-table';

describe('loadLlmRouteTable', () => {
  const RAW = {
    providers: {
      deepseek: { base_url: 'https://api.deepseek.com/v1/', api_key_env: 'TEST_DS_KEY' },
      siliconflow: { base_url: 'https://api.siliconflow.cn/v1', api_key_env: 'TEST_SF_KEY' },
      broken: { base_url: 'https://x.example/v1', api_key_env: 'TEST_MISSING_KEY' },
    },
    models: {
      'deepseek-chat': { provider: 'deepseek', model: 'deepseek-chat' },
      'deepseek-ai/DeepSeek-V3': { provider: 'siliconflow', model: 'deepseek-ai/DeepSeek-V3' },
      'ghost-model': { provider: 'no-such-provider', model: 'x' }, // 漂移：引用不存在的 provider
    },
  };

  beforeEach(() => {
    process.env.TEST_DS_KEY = 'sk-ds-123';
    process.env.TEST_SF_KEY = 'sk-sf-456';
    delete process.env.TEST_MISSING_KEY;
  });

  it('按 api_model 名路由并替换真实模型名', () => {
    const t = loadLlmRouteTable(RAW);
    expect(t.models.get('deepseek-chat')!.model).toBe('deepseek-chat');
    expect(t.models.get('deepseek-chat')!.provider.baseUrl).toBe('https://api.deepseek.com/v1'); // 尾斜杠归一
    expect(t.models.get('deepseek-chat')!.provider.apiKey).toBe('sk-ds-123');
    expect(t.models.get('deepseek-ai/DeepSeek-V3')!.provider.apiKey).toBe('sk-sf-456');
  });

  it('api_key_env 未设置 → apiKey 为空串（调用时 502 PROVIDER_NOT_READY，不炸加载）', () => {
    const t = loadLlmRouteTable(RAW);
    // broken provider 本身保留；引用它的 model 被"model 表"消费时才暴露——
    // 这里验证 provider 条目存在但 key 空
    expect(t.providers.get('broken')!.apiKey).toBe('');
  });

  it('引用不存在 provider 的 model 直接丢弃（表内漂移不静默转发）', () => {
    const t = loadLlmRouteTable(RAW);
    expect(t.models.has('ghost-model')).toBe(false);
  });

  it('缺 providers / models 键 → 空表（fail-closed：全部 404）', () => {
    const t = loadLlmRouteTable({});
    expect(t.providers.size).toBe(0);
    expect(t.models.size).toBe(0);
  });

  it('base_url 缺失 → 空串（502 兜底），不抛异常', () => {
    const t = loadLlmRouteTable({ providers: { x: { api_key_env: 'TEST_DS_KEY' } } });
    expect(t.providers.get('x')!.baseUrl).toBe('');
  });
});
