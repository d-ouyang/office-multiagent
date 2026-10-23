// 分页器（p6.28b）：总数 + 上一页/页码（带省略）+ 下一页 + 每页条数。
// 参考 RAG 管理端 el-pagination 的语义（total, prev, pager, next），不引组件库。
import { useMemo } from 'react';

const PAGE_SIZES = [10, 20, 50, 100];

/** 页码窗口：当前页居中，最多 7 个，越界用 … 折叠。 */
export function pageWindow(current: number, totalPages: number): Array<number | '…'> {
  if (totalPages <= 7) return Array.from({ length: totalPages }, (_, i) => i + 1);
  const pages: Array<number | '…'> = [1];
  const start = Math.max(2, current - 2);
  const end = Math.min(totalPages - 1, current + 2);
  if (start > 2) pages.push('…');
  for (let p = start; p <= end; p += 1) pages.push(p);
  if (end < totalPages - 1) pages.push('…');
  pages.push(totalPages);
  return pages;
}

export default function Pager({
  total,
  page,
  pageSize,
  onPage,
  onPageSize,
}: {
  total: number;
  page: number;
  pageSize: number;
  onPage: (page: number) => void;
  onPageSize?: (size: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / Math.max(1, pageSize)));
  const pages = useMemo(() => pageWindow(page, totalPages), [page, totalPages]);
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);

  return (
    <div className="ui-pager">
      <span className="ui-pager-total">
        共 <strong>{total.toLocaleString()}</strong> 条{total > 0 ? `（${from}-${to}）` : ''}
      </span>
      {onPageSize && (
        <label className="ui-pager-size">
          每页
          <select value={pageSize} onChange={(e) => onPageSize(Number(e.target.value))}>
            {PAGE_SIZES.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
          条
        </label>
      )}
      <div className="ui-pager-pages">
        <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)}>‹</button>
        {pages.map((p, i) =>
          p === '…' ? (
            <span key={`gap-${i}`} className="ui-pager-gap">…</span>
          ) : (
            <button
              key={p}
              type="button"
              className={p === page ? 'on' : ''}
              onClick={() => onPage(p)}
            >
              {p}
            </button>
          ),
        )}
        <button type="button" disabled={page >= totalPages} onClick={() => onPage(page + 1)}>›</button>
      </div>
    </div>
  );
}
