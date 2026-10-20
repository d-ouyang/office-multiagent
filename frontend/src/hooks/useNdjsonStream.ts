// NDJSON 流式 hook：fetch + AbortController + consumeNdjson，收集事件。
// p6.1：start 支持传请求选项（POST /tasks 需要 body + Authorization）。
import { useCallback, useRef, useState } from 'react';

import { consumeNdjson } from '../lib/consume';
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
  const [error, setError] = useState<string | null>(null);
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
        throw new Error(`HTTP ${res.status}`);
      }
      await consumeNdjson(res, (ev) => setEvents((prev) => [...prev, ev]));
      if (!ac.signal.aborted) setStatus('done');
    } catch (e) {
      if ((e as Error).name === 'AbortError') return; // 主动中断不算错误
      setError((e as Error).message);
      setStatus('error');
    }
  }, [defaultUrl]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setStatus('idle');
  }, []);

  return { events, status, error, start, stop };
}
