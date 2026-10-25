import type { MouseEvent, ReactNode } from 'react';

import { Tooltip, message } from './ui';

/** 单行截断；完整内容悬停看。空值和破折号不挂提示。 */
export function Ellipsis({ children, title }: { children: ReactNode; title?: ReactNode }) {
  const text = children == null || children === '' ? '—' : children;
  const tip = title ?? (typeof text === 'string' || typeof text === 'number' ? String(text) : '');
  const node = <span className="admin-ellipsis">{text}</span>;
  if (!tip || tip === '—') return node;
  return <Tooltip title={tip}>{node}</Tooltip>;
}

export async function copyAdminText(value: string): Promise<boolean> {
  const text = value.trim();
  if (!text || text === '—') return false;
  await navigator.clipboard.writeText(text);
  return true;
}

/** 单行省略；点击复制全文，不挂 Tooltip。 */
export function CopyCell({ text }: { text?: string | null }) {
  const value = text?.trim() ? text : '—';
  const onCopy = async (e: MouseEvent) => {
    e.stopPropagation();
    try {
      if (!(await copyAdminText(value))) return;
      message.success('已复制');
    } catch {
      message.error('复制失败');
    }
  };
  return (
    <span className="admin-ellipsis admin-copy-cell" onClick={(e) => void onCopy(e)}>
      {value}
    </span>
  );
}
