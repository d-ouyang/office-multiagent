// NDJSON 流式 hook：fetch + AbortController + consumeNdjson，收集事件。
import { useCallback, useRef, useState } from 'react';

import { consumeNdjson } from '../lib/consume';
import type { StreamEvent } from '../types';

export type StreamStatus = 'idle' | 'streaming' | 'done' | 'error';

export function useNdjsonStream(url: string) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const start = useCallback(async () => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setEvents([]);
    setError(null);
    setStatus('streaming');
    try {
      const res = await fetch(url, {
        signal: ac.signal,
        headers: { Accept: 'application/x-ndjson' },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await consumeNdjson(res, (ev) => setEvents((prev) => [...prev, ev]));
      if (!ac.signal.aborted) setStatus('done');
    } catch (e) {
      if ((e as Error).name === 'AbortError') return; // 主动中断不算错误
      setError((e as Error).message);
      setStatus('error');
    }
  }, [url]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setStatus('idle');
  }, []);

  return { events, status, error, start, stop };
}
