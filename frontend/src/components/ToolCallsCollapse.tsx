// ToolCallsCollapse —— 参考 weight-loss-agent 的同名组件移植（去 tdesign，用 lucide + CSS 变量）。
// 行为对齐 §15.1：按工具类型映射图标、running/completed/error 状态、汇总图标条、
// 最新运行工具置顶、整体折叠/展开、单工具可展开看入参/结果。
import { useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Code2,
  Database,
  Edit3,
  Eye,
  FileText,
  FolderSearch,
  Globe,
  Image as ImageIcon,
  Loader2,
  MessageSquare,
  Search,
  Settings,
  Sparkles,
  Terminal,
  Trash2,
  Wrench,
  XCircle,
  Zap,
} from 'lucide-react';

import type { ToolCall } from '../lib/derive';

const ICONS: Record<string, typeof Wrench> = {
  skill: Sparkles,
  bash: Terminal,
  web_search: Search,
  websearch: Search,
  web_fetch: Globe,
  webfetch: Globe,
  write: FileText,
  read: Eye,
  edit: Edit3,
  delete: Trash2,
  search: FolderSearch,
  image: ImageIcon,
  task: Zap,
  db: Database,
  code: Code2,
  chat: MessageSquare,
  config: Settings,
};

function toolIcon(name: string): typeof Wrench {
  return ICONS[name.toLowerCase()] ?? Wrench;
}

function toolType(name: string): string {
  const n = name.toLowerCase();
  return ICONS[n] ? n : 'other';
}

function statusLabel(tc: ToolCall): string {
  if (tc.status === 'running') return '执行中...';
  if (tc.status === 'error') return '失败';
  return '完成';
}

function StatusIcon({ tc }: { tc: ToolCall }) {
  if (tc.status === 'running') return <Loader2 size={16} className="spin" aria-label="running" />;
  if (tc.status === 'error') return <XCircle size={16} className="ic-error" />;
  return <CheckCircle2 size={16} className="ic-ok" />;
}

function ToolDetail({ tc }: { tc: ToolCall }) {
  const [open, setOpen] = useState(false);
  const Icon = toolIcon(tc.name);
  const inputStr = Object.keys(tc.input).length ? JSON.stringify(tc.input, null, 2) : '';

  return (
    <div className="tool-card">
      <div
        className="tool-head"
        onClick={() => inputStr && setOpen((v) => !v)}
        role={inputStr ? 'button' : undefined}
      >
        <StatusIcon tc={tc} />
        <Icon size={16} />
        <span className="tool-name">{tc.name}</span>
        <span className="tool-status">{statusLabel(tc)}</span>
        {inputStr &&
          (open ? <ChevronUp size={14} /> : <ChevronDown size={14} />)}
      </div>
      {open && inputStr && (
        <div className="tool-body mono">
          <span className="muted">输入: </span>
          {inputStr.length > 300 ? inputStr.slice(0, 300) + '...' : inputStr}
        </div>
      )}
      {tc.result && (
        <div className={`tool-body mono${tc.status === 'error' ? ' err' : ''}`}>
          <span className="muted">{tc.status === 'error' ? '错误: ' : '结果: '}</span>
          {tc.result.length > 500 ? tc.result.slice(0, 500) + '...' : tc.result}
        </div>
      )}
    </div>
  );
}

interface Props {
  toolCalls: ToolCall[];
  isStreaming?: boolean;
}

export function ToolCallsCollapse({ toolCalls, isStreaming = false }: Props) {
  const [expanded, setExpanded] = useState(false);

  const hasRunning = toolCalls.some((t) => t.status === 'running');
  const hasError = toolCalls.some((t) => t.status === 'error');
  const allCompleted = toolCalls.every(
    (t) => t.status === 'completed' || t.status === 'error',
  );

  const summary = useMemo(() => {
    const m = new Map<string, { Icon: typeof Wrench; count: number }>();
    for (const t of toolCalls) {
      const type = toolType(t.name);
      const cur = m.get(type);
      if (cur) cur.count += 1;
      else m.set(type, { Icon: toolIcon(t.name), count: 1 });
    }
    return Array.from(m.entries()).map(([type, v]) => ({ type, ...v }));
  }, [toolCalls]);

  const latestRunningIdx = useMemo(() => {
    for (let i = toolCalls.length - 1; i >= 0; i--) {
      if (toolCalls[i].status === 'running') return i;
    }
    return -1;
  }, [toolCalls]);

  useEffect(() => {
    if (toolCalls.length === 1 && hasRunning) setExpanded(true);
    else if (allCompleted && !isStreaming) setExpanded(false);
  }, [toolCalls.length, hasRunning, allCompleted, isStreaming]);

  const bar = (
    <div className="collapse-bar" onClick={() => setExpanded((v) => !v)} role="button">
      <div className="bar-left">
        {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        {hasRunning ? (
          <Loader2 size={16} className="spin" />
        ) : hasError ? (
          <XCircle size={16} className="ic-error" />
        ) : (
          <CheckCircle2 size={16} className="ic-ok" />
        )}
        <span>{hasRunning ? '执行中...' : expanded ? '收起步骤' : '查看步骤'}</span>
        {toolCalls.length > 1 && <span className="muted">({toolCalls.length})</span>}
      </div>
      <div className="bar-right">
        {summary.map(({ type, Icon, count }) => (
          <span key={type} className="sum-chip" title={`${type} x${count}`}>
            <Icon size={12} />
            {count > 1 && <span className="sum-count">{count}</span>}
          </span>
        ))}
      </div>
    </div>
  );

  // 连续调用：未展开时只显示最新运行中的工具，之前的折叠成"N 个步骤已完成"
  if (hasRunning && !expanded && latestRunningIdx >= 0) {
    return (
      <div className="tcc">
        {latestRunningIdx > 0 && (
          <div className="prev-bar" onClick={() => setExpanded(true)} role="button">
            <div className="bar-left">
              <ChevronDown size={14} />
              <CheckCircle2 size={14} className="ic-ok" />
              <span className="muted">{latestRunningIdx} 个步骤已完成</span>
            </div>
            <div className="bar-right">
              {summary.slice(0, -1).map(({ type, Icon }) => (
                <Icon key={type} size={12} />
              ))}
            </div>
          </div>
        )}
        <ToolDetail tc={toolCalls[latestRunningIdx]} />
      </div>
    );
  }

  return (
    <div className="tcc">
      {bar}
      {expanded && (
        <div className="tcc-list">
          {toolCalls.map((tc) => (
            <ToolDetail key={tc.id} tc={tc} />
          ))}
        </div>
      )}
    </div>
  );
}

export default ToolCallsCollapse;
