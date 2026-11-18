// 模型调用明细（v2.4.3）：一次任务的每次 LLM 调用——收到什么、返回什么、用了多久。
// 数据源 llm_call 表（messages 已脱敏手机号）；列表轻量，逐字内容点开才拉单条。
import { useCallback, useEffect, useState } from 'react';

import {
  adminRunLlmCall,
  adminRunLlmCalls,
  adminToolSchemas,
  type LlmCallDetail,
  type LlmCallRow,
} from '../lib/api';
import { Collapse } from 'antd';
import { Alert, Modal, Table, Tag, Typography } from './ui';

export default function LlmCallsPanel({ runId }: { runId?: string | null }) {
  const [calls, setCalls] = useState<LlmCallRow[]>([]);
  const [detail, setDetail] = useState<LlmCallDetail | null>(null);
  const [schemas, setSchemas] = useState<string>('');
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
      setSchemas(
        data.tools
          .map((t) => `【${t.function.name}】${t.function.description}\n参数: ${JSON.stringify(t.function.parameters)}`)
          .join('\n\n'),
      );
    } catch {
      setSchemas('加载失败');
    }
  };

  if (!runId) return null;

  return (
    <>
      <Collapse
        size="small"
        onChange={(keys: unknown) => {
          if (calls.length === 0) void load();
          void keys;
        }}
        items={[
          {
            key: 'llm',
            label: `模型调用 ${calls.length > 0 ? `（${calls.length} 次）` : ''}`,
            children: (
              <>
                {error && <Alert type="warning" message={error} />}
                <Table
                  size="small"
                  rowKey="id"
                  loading={loading}
                  dataSource={calls}
                  pagination={false}
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
                    if (!schemas) void loadSchemas();
                  }}
                >
                  查看工具 schema（data_analysis）
                </Typography.Link>
              </>
            ),
          },
        ]}
      />
      <Modal
        open={!!detail}
        title={detail ? `第 ${detail.step} 步 · ${detail.agent || '—'} · ${detail.ms ?? 0}ms` : ''}
        footer={null}
        width={720}
        onCancel={() => setDetail(null)}
      >
        {detail && (
          <>
            <Typography.Title level={5}>模型收到（{(detail.messages ?? []).length} 条，手机号已脱敏）</Typography.Title>
            {(detail.messages ?? []).map((m: LlmCallMessage, i: number) => {
              // content 可能是 null（带 tool_calls 的 assistant）或数组（多模态）——直接 .length 会崩掉整个抽屉
              const text = typeof m.content === 'string' ? m.content : JSON.stringify(m.content ?? m.tool_calls ?? null);
              const shown = text.length > 1500 ? `${text.slice(0, 1500)}…（共 ${text.length} 字）` : text;
              return (
                <div key={i} style={{ marginBottom: 10 }}>
                  <Tag>{m.role}</Tag>
                  <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, maxHeight: 240, overflow: 'auto' }}>{shown}</pre>
                </div>
              );
            })}
            <Typography.Title level={5}>模型返回</Typography.Title>
            <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, maxHeight: 240, overflow: 'auto' }}>
              {(detail.response_text || '').slice(0, 2000)}
            </pre>
          </>
        )}
      </Modal>
      <Modal open={!!schemas} title="工具 schema（模型在提示词里看到的名字与说明）" footer={null} width={720} onCancel={() => setSchemas('')}>
        <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, maxHeight: 480, overflow: 'auto' }}>{schemas}</pre>
      </Modal>
    </>
  );
}
