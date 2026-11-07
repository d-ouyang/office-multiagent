import type { AdminRunDetail } from '../lib/api';
import { DRAWER_WIDTH } from './AdminListPage';
import { fmtDuration, fmtShanghai, fmtTokens, REASON, STATUS } from './format';
import FlowPathSvg from './FlowPathSvg';
import { Descriptions, Drawer, Tag, Typography } from './ui';

export default function TaskDetailDrawer({
  detail,
  onClose,
}: {
  detail: AdminRunDetail | null;
  onClose: () => void;
}) {
  if (!detail) {
    return <Drawer open={false} onClose={onClose} />;
  }
  const flow = detail.flow;

  return (
    <Drawer
      open
      title="任务详情"
      width={DRAWER_WIDTH}
      rootClassName="admin-dialog"
      onClose={onClose}
    >
      <Typography.Paragraph type="secondary">
        {fmtShanghai(detail.created_at)} · {fmtDuration(detail.duration_ms)}
      </Typography.Paragraph>
      <div className="admin-detail-head">
        <Tag color={detail.status.startsWith('paused') || detail.status === 'failed' ? 'warning' : 'blue'}>
          {STATUS[detail.status] ?? detail.status}
        </Tag>
        <Typography.Text type="secondary">
          {detail.username ?? '—'}
          {detail.employee_id ? ` · ${detail.employee_id}` : ''}
          {' · '}
          {detail.model || '未记模型'}
        </Typography.Text>
      </div>

      <Typography.Title level={5}>问句</Typography.Title>
      <blockquote className="admin-quote">{detail.text || flow?.question || '—'}</blockquote>

      <Typography.Title level={5}>实走路径</Typography.Title>
      <div className="admin-flow-card">
        <FlowPathSvg flow={flow} />
      </div>

      <Typography.Title level={5}>执行编排</Typography.Title>
      <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label="执行模式">
          {detail.mode === 'multi' ? '多 Agent 协作（multi）' : detail.mode === 'single' ? '单 Agent（single）' : '—'}
        </Descriptions.Item>
        <Descriptions.Item label="Agent 链">
          {detail.agents?.length ? detail.agents.join(' → ') : '—'}
        </Descriptions.Item>
        {detail.mode === 'multi' && detail.subtasks?.length ? (
          <Descriptions.Item label="子任务归属">
            {detail.subtasks.map((s) => `${s.id}→${s.agent}`).join('、')}
          </Descriptions.Item>
        ) : null}
        <Descriptions.Item label="工具来源">
          {detail.mode === 'multi'
            ? '各子任务使用各自 Agent 的固定白名单（agents.yaml）'
            : '主 Agent 的固定白名单（agents.yaml）；能力预检改道时为 general 全量池'}
        </Descriptions.Item>
      </Descriptions>

      <Typography.Title level={5}>关键指标</Typography.Title>
      <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label="用户">{detail.username ?? '—'}</Descriptions.Item>
        <Descriptions.Item label="工号">{detail.employee_id ?? '—'}</Descriptions.Item>
        <Descriptions.Item label="任务耗时">{fmtDuration(detail.duration_ms)}</Descriptions.Item>
        <Descriptions.Item label="消耗 token">{detail.tokens_used ? fmtTokens(detail.tokens_used) : '—'}</Descriptions.Item>
        <Descriptions.Item label="任务原因">{detail.pause_reason ? REASON[detail.pause_reason] ?? detail.pause_reason : '—'}</Descriptions.Item>
        <Descriptions.Item label="任务 id">{detail.id}</Descriptions.Item>
        <Descriptions.Item label="会话 id">{detail.session_id || '—'}</Descriptions.Item>
        <Descriptions.Item label="工具">{detail.tools?.length ? detail.tools.join(' → ') : '无'}</Descriptions.Item>
        <Descriptions.Item label="产物">{detail.artifacts?.length ? detail.artifacts.join('、') : '无'}</Descriptions.Item>
        <Descriptions.Item label="知识库身份">
          <span className={detail.identity_mismatch ? 'warn-text' : ''}>
            调用 {detail.rag_username || '—'}，办公用户 {detail.office_username || detail.username || '—'}
            {detail.identity_mismatch ? '（不一致）' : ''}
          </span>
        </Descriptions.Item>
        {detail.validation_note && (
          <Descriptions.Item label="校验">{detail.validation_note}</Descriptions.Item>
        )}
      </Descriptions>
    </Drawer>
  );
}
