import type { ReactNode } from 'react';

import { Tooltip } from './ui';

/** 单行截断；完整内容悬停看。空值和破折号不挂提示。 */
export function Ellipsis({ children, title }: { children: ReactNode; title?: ReactNode }) {
  const text = children == null || children === '' ? '—' : children;
  const tip = title ?? (typeof text === 'string' || typeof text === 'number' ? String(text) : '');
  const node = <span className="admin-ellipsis">{text}</span>;
  if (!tip || tip === '—') return node;
  return <Tooltip title={tip}>{node}</Tooltip>;
}
