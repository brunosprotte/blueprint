import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

/** Evento da tabela `events` (design master §8). */
export type SddEvent = {
  id: string;
  seq: number;
  demand_id: string | null;
  artifact_id: string | null;
  type: string;
  payload: Record<string, unknown> | null;
  at: string | null;
};

export type StreamStatus = 'connecting' | 'live' | 'polling' | 'offline';

/** O painel guarda os últimos 200 eventos. */
const MAX_EVENTS = 200;

/** Backoff exponencial de reconexão do SSE: 1s, 2s, 4s, 8s, 16s, 30s (teto). */
const BACKOFF_MS = [1000, 2000, 4000, 8000, 16000, 30000];

/** Poll de emergência quando o SSE cai. */
const POLL_MS = 30000;

/**
 * Nomes de evento que o servidor pode declarar via `event:`.
 * O F1 emite `data:` sem `event:` — o `onmessage` cobre esse caso; esta lista
 * cobre o caso de o servidor nomear o evento.
 */
const NAMED_EVENTS = [
  'message',
  'demand.created',
  'demand.claimed',
  'demand.started',
  'demand.merged',
  'demand.closed',
  'demand.blocked',
  'demand.released',
  'demand.reconciled',
  'demand.reconcile_failed',
  'artifact.created',
  'artifact.synced',
  'artifact.promoted',
  'artifact.review_requested',
  'artifact.agents_review_started',
  'artifact.approved',
  'artifact.stabilized',
  'commit.recorded',
  'pipeline_stage',
  'pipeline_completed',
  'review_reported',
  'review_artifact_written',
  'doubts_file_rendered',
  'doubts_catalog_rendered'
];

function normalizeEvent(raw: unknown): SddEvent | null {
  if (!raw || typeof raw !== 'object') return null;
  const record = raw as Record<string, unknown>;
  const id = String(record.id ?? '');
  if (!id) return null;
  const payload =
    record.payload && typeof record.payload === 'object'
      ? (record.payload as Record<string, unknown>)
      : null;
  return {
    id,
    seq: Number(record.id) || 0,
    demand_id: record.demand_id ? String(record.demand_id) : null,
    artifact_id: record.artifact_id ? String(record.artifact_id) : null,
    type: String(record.type ?? 'event'),
    payload,
    at: record.at ? String(record.at) : null
  };
}

export type UseEventStream = {
  events: SddEvent[];
  status: StreamStatus;
  lastEventId: string | null;
};

/**
 * Assina `GET /api/events/stream` (SSE) e mantém um buffer dos últimos 200
 * eventos. Se o SSE cair, reconecta com backoff exponencial e, em paralelo,
 * faz poll de `GET /api/events?demand=&since=` a cada 30s.
 */
export function useEventStream(demandId: string | null): UseEventStream {
  const [events, setEvents] = useState<SddEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>('connecting');
  const storeRef = useRef<Map<string, SddEvent>>(new Map());
  const lastIdRef = useRef<string | null>(null);

  const apply = useCallback((incoming: SddEvent[]) => {
    if (incoming.length === 0) return;
    const store = storeRef.current;
    for (const event of incoming) {
      store.set(event.id, event);
      if (lastIdRef.current === null || event.seq > Number(lastIdRef.current)) {
        lastIdRef.current = event.id;
      }
    }
    const sorted = [...store.values()].sort((a, b) => a.seq - b.seq);
    const trimmed = sorted.slice(-MAX_EVENTS);
    const keep = new Set(trimmed.map((event) => event.id));
    for (const key of [...store.keys()]) {
      if (!keep.has(key)) store.delete(key);
    }
    setEvents(trimmed);
  }, []);

  // SSE — conexão independente da demanda selecionada (o filtro é do cliente).
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.EventSource === 'undefined') {
      setStatus('offline');
      return undefined;
    }

    let source: EventSource | null = null;
    let retry: number | undefined;
    let attempt = 0;
    let stopped = false;

    const connect = () => {
      if (stopped) return;
      // URL relativa: same-origin, o cookie `sdd_session` vai junto sem CORS.
      source = new window.EventSource('/api/events/stream');
      source.onopen = () => {
        attempt = 0;
        setStatus('live');
      };
      const handle = (message: MessageEvent) => {
        try {
          const parsed = normalizeEvent(JSON.parse(message.data as string));
          if (parsed) apply([parsed]);
        } catch {
          // payload fora do formato esperado: ignora o frame, não derruba o stream
        }
      };
      source.onmessage = handle;
      for (const name of NAMED_EVENTS) {
        source.addEventListener(name, handle as EventListener);
      }
      source.onerror = () => {
        setStatus('polling');
        source?.close();
        const delay = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)];
        attempt += 1;
        retry = window.setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      stopped = true;
      if (retry !== undefined) window.clearTimeout(retry);
      source?.close();
    };
  }, [apply]);

  // Poll de emergência — assume quando o SSE não está delivering.
  useEffect(() => {
    if (!demandId) return undefined;

    const poll = async () => {
      try {
        const params = new URLSearchParams({ demand: demandId });
        if (lastIdRef.current) params.set('since', lastIdRef.current);
        const response = await fetch(`/api/events?${params.toString()}`, {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' }
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = await response.json();
        const list = Array.isArray(body)
          ? body
          : ((body?.events ?? body?.items ?? []) as unknown[]);
        const parsed = list
          .map(normalizeEvent)
          .filter((event): event is SddEvent => event !== null);
        apply(parsed);
      } catch {
        // servidor fora: o poll tenta de novo em 30s e o SSE reconecta com backoff
      }
    };

    void poll();
    const timer = window.setInterval(() => {
      void poll();
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [demandId, apply]);

  const filtered = useMemo(
    () => (demandId ? events.filter((event) => event.demand_id === demandId) : events),
    [events, demandId]
  );

  return { events: filtered, status, lastEventId: lastIdRef.current };
}
