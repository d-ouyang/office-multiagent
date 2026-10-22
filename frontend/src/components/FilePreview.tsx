// 预览本人已上传到服务器的文件。md/txt 直接显示文本，pdf 用浏览器内嵌打开。
import { useEffect, useState } from 'react';

import { authHeaders } from '../lib/api';

function fileLabel(path: string): string {
  return path.split('/').pop() || path;
}

export function FilePreview({ path, onClose }: { path: string; onClose: () => void }) {
  const name = fileLabel(path);
  const lower = name.toLowerCase();
  const isPdf = lower.endsWith('.pdf');
  const isImage = lower.endsWith('.svg') || lower.endsWith('.png');
  const [text, setText] = useState('');
  const [pdfUrl, setPdfUrl] = useState('');
  const [imageUrl, setImageUrl] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let url = '';
    const ac = new AbortController();
    (async () => {
      try {
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
  }, [path, isPdf, isImage]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="file-preview-backdrop" onClick={onClose}>
      <div className="file-preview" role="dialog" aria-label={`预览 ${name}`} onClick={(e) => e.stopPropagation()}>
        <header>
          <div>
            <div className="file-preview-kicker">服务器上的文件</div>
            <strong>{name}</strong>
          </div>
          <button type="button" className="ghost" onClick={onClose}>关闭</button>
        </header>
        {error && <p className="account-err">{error}</p>}
        {!error && isPdf && pdfUrl && <iframe title={name} src={pdfUrl} />}
        {!error && isImage && imageUrl && <img src={imageUrl} alt={name} />}
        {!error && !isPdf && !isImage && <pre>{text || '正在读取…'}</pre>}
      </div>
    </div>
  );
}

export default FilePreview;
