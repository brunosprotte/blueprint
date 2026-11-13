import React from 'react';
import type { SddEvent } from './useEventStream';
import styles from './styles.module.css';

type Props = {
  events: SddEvent[];
};

/** Resumo curto do payload do evento. */
function summarize(payload: Record<string, unknown> | null): string {
  if (!payload) return '';
  const parts: string[] = [];
  for (const [key, value] of Object.entries(payload)) {
    if (value === null || value === undefined) continue;
    if (typeof value === 'object') continue;
    parts.push(`${key}=${String(value)}`);
  }
  return parts.join(' · ');
}

/** Timeline de eventos da demanda selecionada. */
export default function EventTimeline({ events }: Props): React.ReactNode {
  if (events.length === 0) {
    return <p className={styles.empty}>Nenhum evento para esta demanda.</p>;
  }

  const ordered = [...events].sort((a, b) => b.seq - a.seq);

  return (
    <ol className={styles.timeline}>
      {ordered.map((event) => (
        <li key={event.id} className={styles.timelineItem}>
          <span className={styles.timelineType}>{event.type}</span>
          <span className={styles.timelineAt}>{event.at ?? '—'}</span>
          {event.payload ? (
            <span className={styles.timelinePayload}>{summarize(event.payload)}</span>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
