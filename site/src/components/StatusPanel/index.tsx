import React, { useCallback, useEffect, useState } from 'react';
import clsx from 'clsx';
import ApproveButton from './ApproveButton';
import EventTimeline from './EventTimeline';
import StatusTable from './StatusTable';
import { DEMAND_STATUSES, useDemands } from './useDemands';
import { useEventStream } from './useEventStream';
import styles from './styles.module.css';

type ArtifactRef = {
  id: string;
  kind?: string;
  path?: string;
  status?: string;
};

/** `GET /api/demands/{id}` devolve a demanda mais `artifacts` e `events`. */
type DemandDetail = {
  artifacts?: ArtifactRef[];
};

const STREAM_LABEL: Record<string, string> = {
  connecting: 'conectando',
  live: 'ao vivo (SSE)',
  polling: 'poll de 30s',
  offline: 'offline'
};

/**
 * Painel de status — o único componente vivo do site.
 *
 * Mostra, não decide: a única escrita é a aprovação explícita de artefato,
 * disparada por clique humano (design master §15.2).
 */
export default function StatusPanel(): React.ReactNode {
  const {
    demands,
    repos,
    statusFilter,
    setStatusFilter,
    repoFilter,
    setRepoFilter,
    loading,
    error,
    reload
  } = useDemands();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactRef[]>([]);
  const { events, status } = useEventStream(selectedId);

  const loadArtifacts = useCallback(async (demandId: string) => {
    try {
      const response = await fetch(`/api/demands/${encodeURIComponent(demandId)}`, {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' }
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body = (await response.json()) as DemandDetail;
      setArtifacts(Array.isArray(body?.artifacts) ? body.artifacts : []);
    } catch {
      setArtifacts([]);
    }
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setArtifacts([]);
      return;
    }
    void loadArtifacts(selectedId);
  }, [selectedId, loadArtifacts]);

  // Evento de demanda recarrega a tabela — o painel reflete o servidor.
  const lastEvent = events.length > 0 ? events[events.length - 1] : null;
  useEffect(() => {
    if (lastEvent && lastEvent.type.startsWith('demand.')) {
      void reload();
    }
  }, [lastEvent, reload]);

  const selected = demands.find((demand) => demand.id === selectedId) ?? null;
  const pending = artifacts.filter((artifact) => artifact.status === 'on agents review');

  return (
    <section className={styles.panel}>
      <div className={styles.filters}>
        <label className={styles.filter}>
          <span>Status</span>
          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <option value="">Todos</option>
            {DEMAND_STATUSES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.filter}>
          <span>Repositório</span>
          <select value={repoFilter} onChange={(event) => setRepoFilter(event.target.value)}>
            <option value="">Todos</option>
            {repos.map((repo) => (
              <option key={repo} value={repo}>
                {repo}
              </option>
            ))}
          </select>
        </label>

        <button type="button" className={styles.reload} onClick={() => void reload()}>
          Recarregar
        </button>

        <span className={clsx(styles.stream, styles[`stream-${status}`])}>
          Eventos: {STREAM_LABEL[status] ?? status}
        </span>
      </div>

      {error ? <p className={styles.error}>Falha ao carregar demandas: {error}</p> : null}
      {loading ? <p className={styles.empty}>Carregando…</p> : null}

      <StatusTable demands={demands} selectedId={selectedId} onSelect={setSelectedId} />

      {selected ? (
        <div className={styles.detail}>
          <h2 className={styles.detailTitle}>{selected.title}</h2>

          <h3 className={styles.detailHeading}>Aprovação de artefato</h3>
          {pending.length === 0 ? (
            <p className={styles.empty}>Nenhum artefato em “on agents review”.</p>
          ) : (
            <ul className={styles.artifactList}>
              {pending.map((artifact) => (
                <li key={artifact.id}>
                  <span className={styles.artifactId}>{artifact.id}</span>
                  {artifact.path ? (
                    <span className={styles.artifactPath}>{artifact.path}</span>
                  ) : null}
                  <ApproveButton artifactId={artifact.id} />
                </li>
              ))}
            </ul>
          )}

          <h3 className={styles.detailHeading}>Timeline</h3>
          <EventTimeline events={events} />
        </div>
      ) : (
        <p className={styles.empty}>Selecione uma demanda para ver a timeline.</p>
      )}
    </section>
  );
}
