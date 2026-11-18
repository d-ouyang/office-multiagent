// 模型调用明细（v2.4.3）：一次任务的每次 LLM 调用——收到什么、返回什么、用了多久。
// 设计：分层渲染——统计条 → 按角色分块的消息（system 折叠）→ 返回 JSON 解析成
// "思考 / 动作 / 参数"三段。数据源 llm_call 表（手机号已脱敏）。
import { useCallback, useEffect, useState } from 'react';

import { Collapse } from 'antd';
import {
  adminRunLlmCall,
  adminRunLlmCalls,
  adminToolSchemas,
  type LlmCallDetail,
  type LlmCallMessage,
  type LlmCallRow,
} from '../lib/api';
import { Alert, Modal, Table, Tag, Typography } from './ui';

const ROLE_META: Record<string, { color: string; label: string }> = {
  system: { color: '#8b93a7', label: '系统提示' },
  user: { color: '#60a5fa', label: '用户输入' },
  assistant: { color: '#34d399', label: '模型输出' },
  tool: { color: '#f59e0b', label: '工具结果' },
};

function safeText(content: unknown): string {
  if (typeof content === 'string') return content;
  try {
    return JSON.stringify(content ?? null, null, 2);
  } catch {
    return String(content);
  }
}

function MessageCard({ role, content }: { role: string; content: unknown }) {
  const meta = ROLE_META[role] ?? { color: '#8b93a7', label: role };
  const text = safeText(content);
  const head = (
    <div className="llm-msg-head">
      <span className="llm-role" style={{ color: meta.color, borderColor: meta.color }}>
        {meta.label}
      </span>
      <span className="llm-len">{text.length.toLocaleString()} 字</span>
    </div>
  );
  const body = <pre className="llm-pre">{text}</pre>;
  return (
    <div className="llm-msg">
      {head}
      {/* system 提示很长且每次相同——默认折叠，工具/user/assistant 直接展示 */}
      {role === 'system' ? (
        <Collapse
          size="small"
          items={[{ key: 'sys', label: `展开查看（${text.length.toLocaleString()} 字）`, children: body }]}
        />
      ) : (
        body
      )}
    </div>
  );
}

/** 模型返回：JSON 协议解析成 思考 / 动作 / 参数 三段；解析失败回落原文。 */
function ResponseView({ text }: { text: string }) {
  let parsed: {
    thought?: string;
    action?: string;
    action_input?: Record<string, unknown>;
    final?: string;
  } | null = null;
  try {
    const j = JSON.parse(text);
    if (j && typeof j === 'object' && (j.thought || j.action || j.final)) parsed = j;
  } catch {
    /* 非协议 JSON（如终答自然语言）→ 原文展示 */
  }
  if (!parsed) {
    return <pre className="llm-pre">{text.slice(0, 2000) || '（空）'}</pre>;
  }
  if (parsed.final) {
    return (
      <div className="llm-msg">
        <div className="llm-msg-head">
          <span className="llm-role" style={{ color: '#34d399', borderColor: '#34d399' }}>
            终答（直接写给用户）
          </span>
        </div>
        <pre className="llm-pre">{String(parsed.final).slice(0, 1200)}</pre>
      </div>
    );
  }
  const args = Object.entries(parsed.action_input ?? {});
  return (
    <div className="llm-resp">
      {parsed.thought && (
        <>
          <div className="llm-resp-label">思考</div>
          <div className="llm-thought">{parsed.thought}</div>
        </>
      )}
      {parsed.action && (
        <>
          <div className="llm-resp-label">调用动作</div>
          <div className="llm-action">
            <Tag color="blue">{parsed.action}</Tag>
          </div>
        </>
      )}
      {args.length > 0 && (
        <>
          <div className="llm-resp-label">参数</div>
          <div className="llm-args">
            {args.map(([k, v]) => (
              <div key={k} className="llm-arg">
                <code>{k}</code> = <code>{JSON.stringify(v)}</code>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="llm-stat">
      <b>{value}</b>
      <span>{label}</span>
    </div>
  );
}

/** 工具 schema 卡片：description 与参数定义分开渲染，参数逐行成表。 */
function ToolSchemaCard({
  name,
  description,
  parameters,
}: {
  name: string;
  description: string;
  parameters: {
    properties?: Record<string, { type?: unknown; description?: string; enum?: string[] }>;
    required?: string[];
  } | null;
}) {
  const props = parameters?.properties ?? {};
  const required: string[] = parameters?.required ?? [];
  const firstSentence = `${description.split('。')[0] ?? ''}。`;
  const paramRows = Object.entries(props);
  return (
    <div className="llm-tool">
      <div className="llm-tool-head">
        <code className="llm-tool-name">{name}</code>
        <span className="llm-len">{paramRows.length} 个参数</span>
      </div>
      <div className="llm-tool-desc">{firstSentence}</div>
      <Collapse
        size="small"
        items={[
          {
            key: 'desc',
            label: `完整说明（${description.length.toLocaleString()} 字）`,
            children: <pre className="llm-pre">{description}</pre>,
          },
          {
            key: 'params',
            label: '参数定义',
            children:
              paramRows.length === 0 ? (
                <div className="llm-tool-desc">（无参数）</div>
              ) : (
                <table className="llm-params">
                  <thead>
                    <tr>
                      <th>参数</th>
                      <th>类型</th>
                      <th>必填</th>
                      <th>说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    {paramRows.map(([k, v]) => (
                      <tr key={k}>
                        <td>
                          <code className="llm-tool-name">{k}</code>
                          {required.includes(k) && <span className="llm-req">*</span>}
                        </td>
                        <td>{Array.isArray(v.type) ? v.type.join(' | ') : String(v.type ?? '—')}</td>
                        <td>{required.includes(k) ? <Tag color="red">必填</Tag> : '可选'}</td>
                        <td>{v.description ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ),
          },
        ]}
      />
    </div>
  );
}

export default function LlmCallsPanel({ runId }: { runId?: string | null }) {
  const [calls, setCalls] = useState<LlmCallRow[]>([]);
  const [detail, setDetail] = useState<LlmCallDetail | null>(null);
  const [schemas, setSchemas] = useState<string>('');
  const [schemaData, setSchemaData] = useState<ReturnType<typeof adminToolSchemas> | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!runId) return;
    setLoading(true);
    try {
      setCalls(await adminRunLlmCalls(runId));
      setError('');
    } catch {
      setCalls([]);
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load]);

  const openDetail = async (callId: number) => {
    try {
      setDetail(await adminRunLlmCall(runId ?? '', callId));
    } catch {
      setDetail(null);
    }
  };

  const loadSchemas = async () => {
    try {
      const data = await adminToolSchemas('data_analysis');
      setSchemaData(data);
    } catch {
      setSchemas('加载失败');
    }
  };

  if (!runId) return null;

  return (
    <>
      <Collapse
        size="small"
        onChange={() => {
          if (calls.length === 0) void load();
        }}
        items={[
          {
            key: 'llm',
            label: `模型调用 ${calls.length > 0 ? `（${calls.length} 次）` : ''}`,
            children: (
              <>
                {error && <Alert type="warning" message={error} />}
                {calls.length === 0 && !loading && (
                  <div className="llm-tool-desc">该任务没有模型调用记录（旧版本任务或记录失败）。</div>
                )}
                <Table
                  size="small"
                  rowKey="id"
                  loading={loading}
                  dataSource={calls}
                  pagination={calls.length > 8 ? { pageSize: 8, showSizeChanger: false } : false}
                  onRow={(r) => ({ onClick: () => void openDetail(r.id), style: { cursor: 'pointer' } })}
                  columns={[
                    { title: '#', dataIndex: 'step', width: 40 },
                    { title: 'Agent', dataIndex: 'agent', width: 130, ellipsis: true },
                    { title: '输入', dataIndex: 'prompt_tokens', width: 80, align: 'right' },
                    { title: '输出', dataIndex: 'completion_tokens', width: 70, align: 'right' },
                    { title: '耗时', dataIndex: 'ms', width: 80, align: 'right', render: (v: number) => `${v ?? 0}ms` },
                  ]}
                />
                <Typography.Link
                  onClick={() => {
                    if (!schemaData) void loadSchemas();
                  }}
                >
                  查看工具 schema（data_analysis 工具池）
                </Typography.Link>
              </>
            ),
          },
        ]}
      />
      <Modal
        open={!!detail}
        title={detail ? `第 ${detail.step} 步 · ${detail.agent || '—'}` : ''}
        footer={null}
        width={760}
        onCancel={() => setDetail(null)}
      >
        {detail && (
          <>
            <div className="llm-stats">
              <Stat label="模型" value={detail.model || '—'} />
              <Stat label="输入 tokens" value={(detail.prompt_tokens ?? 0).toLocaleString()} />
              <Stat label="输出 tokens" value={(detail.completion_tokens ?? 0).toLocaleString()} />
              <Stat label="耗时" value={`${detail.ms ?? 0}ms`} />
            </div>
            <Typography.Title level={5}>模型收到（{(detail.messages ?? []).length} 条，手机号已脱敏）</Typography.Title>
            {(detail.messages ?? []).map((m: LlmCallMessage, i: number) => (
              <MessageCard key={i} role={m.role} content={m.content} />
            ))}
            <Typography.Title level={5}>模型返回</Typography.Title>
            <ResponseView text={detail.response_text || ''} />
          </>
        )}
      </Modal>
      <Modal
        open={!!schemas || !!schemaData}
        title="工具 schema —— 模型在提示词里看到的名字与说明"
        footer={null}
        width={760}
        onCancel={() => {
          setSchemas('');
          setSchemaData(null);
        }}
      >
        {schemas && <Alert type="warning" message={schemas} />}
        {schemaData &&
          schemaData.tools.map((t) => (
            <ToolSchemaCard
              key={t.function.name}
              name={t.function.name}
              description={t.function.description}
              parameters={t.function.parameters as never}
            />
          ))}
      </Modal>
    </>
  );
}
