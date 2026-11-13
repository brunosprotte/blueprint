import { useCallback, useEffect, useMemo, useState } from 'react';

/** Status canônicos de `demands` (design master §8). */
export const DEMAND_STATUSES = [
  'open',
  'claimed',
  'in_progress',
  'review',
  'merged',
  'done',
  'blocked'
] as const;

export type Demand = {
  id: string;
  title: string;
  module: string;
  status: string;
  owner: string;
  repo: string;
  updated_at: string | null;
};

/** Forma crua do item de `GET /api/demands` — campos são tolerantes. */
type RawDemand = {
  id?: string;
  title?: string;
  module?: string;
  status?: string;
  owner?: { login?: string; name?: string; id?: string } | string | null;
  claimed_by?: string | null;
  repo?: string | null;
  repo_id?: string | null;
  updated_at?: string | null;
};

function ownerOf(demand: RawDemand): string {
  const owner = demand.owner;
  if (owner && typeof owner === 'object') {
    return String(owner.login ?? owner.name ?? owner.id ?? '—');
  }
  if (typeof owner === 'string' && owner.trim()) return owner;
  if (demand.claimed_by) return String(demand.claimed_by);
  return '—';
}

function normalize(raw: RawDemand): Demand {
  return {
    id: String(raw.id ?? ''),
    title: String(raw.title ?? raw.id ?? '—'),
    module: String(raw.module ?? '—'),
    status: String(raw.status ?? '—'),
    owner: ownerOf(raw),
    repo: String(raw.repo ?? raw.repo_id ?? '—'),
    updated_at: raw.updated_at ?? null
  };
}

/** Parse tolerante da lista: array puro, `{demands: []}` ou `{items: []}`. */
function extractList(body: unknown): RawDemand[] {
  if (Array.isArray(body)) return body as RawDemand[];
  if (body && typeof body === 'object') {
    const record = body as Record<string, unknown>;
    if (Array.isArray(record.demands)) return record.demands as RawDemand[];
    if (Array.isArray(record.items)) return record.items as RawDemand[];
  }
  return [];
}

export type UseDemands = {
  demands: Demand[];
  repos: string[];
  statusFilter: string;
  setStatusFilter: (value: string) => void;
  repoFilter: string;
  setRepoFilter: (value: string) => void;
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
};

export function useDemands(): UseDemands {
  const [all, setAll] = useState<Demand[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [repoFilter, setRepoFilter] = useState('');

  const reload = useCallback(async () => {
    try {
      const response = await fetch('/api/demands', {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' }
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body = await response.json();
      setAll(extractList(body).map(normalize));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const repos = useMemo(() => {
    const unique = new Set<string>();
    for (const demand of all) {
      if (demand.repo && demand.repo !== '—') unique.add(demand.repo);
    }
    return [...unique].sort();
  }, [all]);

  const demands = useMemo(
    () =>
      all.filter(
        (demand) =>
          (!statusFilter || demand.status === statusFilter) &&
          (!repoFilter || demand.repo === repoFilter)
      ),
    [all, statusFilter, repoFilter]
  );

  return {
    demands,
    repos,
    statusFilter,
    setStatusFilter,
    repoFilter,
    setRepoFilter,
    loading,
    error,
    reload
  };
}
