// NDJSON 流式 hook：fetch + AbortController + consumeNdjson，收集事件。
// p6.1：start 支持传请求选项（POST /tasks 需要 body + Authorization）。
// v2.4.1：非 2xx 时解析响应体成 ApiError（此前只抛 `HTTP 429`，把后端的
//         {"detail":{"code":"BALANCE_INSUFFICIENT","message":"余额不足…"}} 整段丢掉）。
import { useCallback, useRef, useState } from 'react';

import { consumeNdjson } from '../lib/consume';
import { ApiError, parseApiError } from '../lib/apiError';
import type { StreamEvent } from '../types';

export type StreamStatus = 'idle' | 'streaming' | 'done' | 'error';

export interface StartOptions {
  url?: string;
  method?: 'GET' | 'POST';
  body?: unknown;
  headers?: Record<string, string>;
  /** 401 时回调（token 过期/无效 → 上层清登录态） */
  on401?: () => void;
}

export function useNdjsonStream(defaultUrl: string) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>('idle');
  const [error, setError] = useState<Error | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const start = useCallback(async (opts?: StartOptions) => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setEvents([]);
    setError(null);
    setStatus('streaming');
    try {
      const res = await fetch(opts?.url ?? defaultUrl, {
        method: opts?.method ?? 'GET',
        signal: ac.signal,
        headers: {
          Accept: 'application/x-ndjson',
          ...(opts?.body ? { 'Content-Type': 'application/json' } : {}),
          ...(opts?.headers ?? {}),
        },
        body: opts?.body ? JSON.stringify(opts.body) : undefined,
      });
      if (!res.ok) {
        if (res.status === 401 && opts?.on401) opts.on401();
        throw await readApiError(res);
      }
      await consumeNdjson(res, (ev) => setEvents((prev) => [...prev, ev]));
      if (!ac.signal.aborted) setStatus('done');
    } catch (e) {
      if ((e as Error).name === 'AbortError') return; // 主动中断不算错误
      setError(e instanceof Error ? e : new Error(String(e)));
      setStatus('error');
    }
  }, [defaultUrl]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setStatus('idle');
  }, []);

  /** 清空当前流（p6.2：消息固化/切会话时用）。 */
  const reset = useCallback(() => {
    setEvents([]);
    setStatus('idle');
    setError(null);
  }, []);

  /** 只关掉错误提示，不动已收到的消息（v2.4.1：Notice 的关闭按钮用）。 */
  const clearError = useCallback(() => setError(null), []);

  return { events, status, error, start, stop, reset, clearError };
}

/** 读响应体 → ApiError。body 不是 JSON（502 网关页等）时退化为状态码文案。 */
async function readApiError(res: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  return parseApiError(res.status, body);
}

