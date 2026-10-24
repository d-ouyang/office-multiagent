// 文件预览浮层：表格（csv/xlsx）分页增量加载（滚动到底自动取下一页），pdf/图片内嵌，其余文本直读。
// 原则：界面文案不出现技术名词（服务器/后端/接口等），只说用户能感知的东西。
import { useCallback, useEffect, useRef, useState } from 'react';

import { authHeaders } from '../lib/api';

const PAGE_SIZE = 50;

function fileLabel(path: string): string {
  return path.split('/').pop() || path;
}

function kindBadge(name: string): string {
  const lower = name.toLowerCase();
  if (lower.endsWith('.csv') || lower.endsWith('.xlsx')) return '表格';
  if (lower.endsWith('.pdf')) return 'PDF';
  if (lower.endsWith('.pptx')) return '演示文稿';
  if (lower.endsWith('.docx')) return '文档';
  if (['.svg', '.png', '.jpg', '.jpeg', '.webp'].some((s) => lower.endsWith(s))) return '图片';
  return '文件';
}

async function downloadFile(path: string, name: string) {
  const res = await fetch(`/api/v1/documents/content?name=${encodeURIComponent(path)}&download=true`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error('download failed');
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

interface TablePage {
  columns: string[];
  rows: string[][];
  total: number;
  sheets: string[];
  sheet: string | null;
}

/** 表格分页加载：追加式（滚动到底自动取下一页），切工作表重置。 */
function useTable(path: string, sheet: string) {
  const [page, setPage] = useState<TablePage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const offsetRef = useRef(0);
  const totalRef = useRef(Infinity);

  const load = useCallback(
    async (reset: boolean, targetSheet: string) => {
      if (loading) return;
      const offset = reset ? 0 : offsetRef.current;
      if (!reset && offset >= totalRef.current) return;
      setLoading(true);
      try {
        const qs = new URLSearchParams({ name: path, offset: String(offset), limit: String(PAGE_SIZE) });
        if (targetSheet) qs.set('sheet', targetSheet);
        const res = await fetch(`/api/v1/documents/table?${qs}`, { headers: authHeaders() });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          setError(String(data?.detail?.message ?? '这份表格暂时读不出来'));
          return;
        }
        offsetRef.current = offset + (data.rows?.length ?? 0);
        totalRef.current = data.total ?? 0;
        setError(null);
        setPage((prev) =>
          reset
            ? {
                columns: data.columns ?? [],
                rows: data.rows ?? [],
                total: data.total ?? 0,
                sheets: data.sheets ?? [],
                sheet: data.sheet ?? null,
              }
            : {
                ...prev!,
                rows: [...(prev?.rows ?? []), ...(data.rows ?? [])],
              },
        );
      } catch {
        setError('这份表格暂时读不出来');
      } finally {
        setLoading(false);
      }
    },
    [path, loading],
  );

  useEffect(() => {
    offsetRef.current = 0;
    totalRef.current = Infinity;
    setPage(null);
    void load(true, sheet);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, sheet]);

  return { page, error, loading, loadMore: () => load(false, sheet) };
}

export function FilePreview({ path, onClose }: { path: string; onClose: () => void }) {
  const name = fileLabel(path);
  const lower = name.toLowerCase();
  const isPdf = lower.endsWith('.pdf');
  const isImage = ['.svg', '.png', '.jpg', '.jpeg', '.webp'].some((suffix) => lower.endsWith(suffix));
  const isTable = lower.endsWith('.csv') || lower.endsWith('.xlsx');
  const [sheets, setSheets] = useState<string[]>([]);
  const [sheet, setSheet] = useState('');
  const { page, error: tableError, loading, loadMore } = useTable(path, sheet);
  const [text, setText] = useState('');
  const [pdfUrl, setPdfUrl] = useState('');
  const [imageUrl, setImageUrl] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setSheets([]);
    setSheet('');
    let url = '';
    const ac = new AbortController();
    (async () => {
      try {
        if (isTable) return; // 表格走分页接口
        const res = await fetch(`/api/v1/documents/content?name=${encodeURIComponent(path)}`, {
          headers: authHeaders(),
          signal: ac.signal,
        });
        if (!res.ok) {
          setError('打不开这份文件');
          return;
        }
        if (isPdf || isImage) {
          url = URL.createObjectURL(await res.blob());
          if (isPdf) setPdfUrl(url);
          else setImageUrl(url);
        } else {
          setText(await res.text());
        }
      } catch (e) {
        if ((e as Error).name !== 'AbortError') setError('打不开这份文件');
      }
    })();
    return () => {
      ac.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [path, isPdf, isImage, isTable]);

  // 表格工作表列表（xlsx 多表时可切换）
  useEffect(() => {
    if (!isTable || !page) return;
    if (page.sheets.length > 1 && sheets.length === 0) {
      setSheets(page.sheets);
      setSheet(page.sheet ?? page.sheets[0]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, isTable]);

  // 滚动到底自动加载下一页
  useEffect(() => {
    if (!isTable || !sentinelRef.current || !scrollRef.current) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !loading && page && page.rows.length < page.total) {
          void loadMore();
        }
      },
      { root: scrollRef.current, rootMargin: '200px' },
    );
    observer.observe(sentinelRef.current);
    return () => observer.disconnect();
  }, [isTable, loading, page, loadMore]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const onDownload = async () => {
    setBusy(true);
    try {
      await downloadFile(path, name);
    } catch {
      setError('没下载成功，请再试一次');
    } finally {
      setBusy(false);
    }
  };

  const shown = page?.rows.length ?? 0;
  return (
    <div className="file-preview-backdrop" onClick={onClose}>
      <div className="file-preview" role="dialog" aria-label={`预览 ${name}`} onClick={(e) => e.stopPropagation()}>
        <header>
          <div>
            <div className="file-preview-kicker">
              <span className="file-kind">{kindBadge(name)}</span>
            </div>
            <strong>{name}</strong>
          </div>
          <div className="file-preview-ops">
            <button type="button" className="ghost" disabled={busy} onClick={() => void onDownload()}>
              {busy ? '下载中…' : '下载'}
            </button>
            <button type="button" className="ghost" onClick={onClose}>关闭</button>
          </div>
        </header>
        {error && <p className="account-err">{error}</p>}
        {!error && isPdf && pdfUrl && <iframe title={name} src={pdfUrl} />}
        {!error && isImage && imageUrl && <img src={imageUrl} alt={name} />}
        {!error && isTable && (
          <div className="file-preview-scroll" ref={scrollRef}>
            {sheets.length > 1 && (
              <div className="sheet-tabs" role="tablist" aria-label="工作表">
                {sheets.map((s) => (
                  <button
                    key={s}
                    type="button"
                    role="tab"
                    aria-selected={s === sheet}
                    className={`sheet-tab ${s === sheet ? 'active' : ''}`}
                    onClick={() => setSheet(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
            {!page && !tableError && <p className="account-note">正在读取…</p>}
            {tableError && <p className="account-err">{tableError}</p>}
            {page && (
              <>
                <table className="preview-table">
                  <thead>
                    <tr>
                      {page.columns.map((c, i) => (
                        <th key={`${c}-${i}`}>{c || `列${i + 1}`}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {page.rows.map((row, ri) => (
                      <tr key={ri}>
                        {page.columns.map((_, ci) => (
                          <td key={ci}>{row[ci] ?? ''}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div ref={sentinelRef} aria-hidden="true" />
                <p className="preview-table-meta">
                  {loading ? '正在加载…' : shown < page.total ? '继续滚动加载' : '已全部加载'}
                  {` · 共 ${page.total.toLocaleString('zh-CN')} 行，已显示 ${shown.toLocaleString('zh-CN')} 行`}
                </p>
              </>
            )}
          </div>
        )}
        {!error && !isPdf && !isImage && !isTable && <pre>{text || '正在读取…'}</pre>}
      </div>
    </div>
  );
}

export default FilePreview;
