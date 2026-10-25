import type { MouseEvent, ReactNode } from 'react';

import { message } from './ui';

/** 单行截断，不挂悬停提示。 */
export function Ellipsis({ children }: { children: ReactNode; title?: ReactNode }) {
  const text = children == null || children === '' ? '—' : children;
  return <span className="admin-ellipsis">{text}</span>;
}

export async function copyAdminText(value: string): Promise<boolean> {
  const text = value.trim();
  if (!text || text === '—') return false;
  await navigator.clipboard.writeText(text);
  return true;
}

/** 单行省略；点击复制全文，不挂 Tooltip。 */
export function CopyCell({ text, className }: { text?: string | null; className?: string }) {
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
    <span className={`admin-ellipsis admin-copy-cell${className ? ` ${className}` : ''}`} onClick={(e) => void onCopy(e)}>
      {value}
    </span>
  );
}
