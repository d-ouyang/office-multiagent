import type { ReactNode } from 'react';

import { Pagination } from './ui';

export const PAGE_SIZE = 20;
export const DRAWER_WIDTH = 'min(1080px, 86vw)';

export function AdminListPage({
  filters,
  extra,
  children,
  footer,
}: {
  filters?: ReactNode;
  extra?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="admin-list-page">
      {filters && <div className="admin-filter-bar">{filters}</div>}
      {extra && <div className="admin-list-extra">{extra}</div>}
      <div className="admin-list-body">{children}</div>
      {footer && <div className="admin-list-pager">{footer}</div>}
    </div>
  );
}

export function AdminPager({
  total,
  page,
  onChange,
  unit = '条',
}: {
  total: number;
  page: number;
  onChange: (page: number) => void;
  unit?: string;
}) {
  return (
    <Pagination
      current={page}
      pageSize={PAGE_SIZE}
      total={total}
      showSizeChanger={false}
      showQuickJumper={false}
      showLessItems
      showTotal={(n) => `共 ${n} ${unit}`}
      onChange={onChange}
    />
  );
}
