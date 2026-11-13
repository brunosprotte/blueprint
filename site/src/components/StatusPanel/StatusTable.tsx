import React from 'react';
import clsx from 'clsx';
import type { Demand } from './useDemands';
import styles from './styles.module.css';

type Props = {
  demands: Demand[];
  selectedId: string | null;
  onSelect: (id: string) => void;
};

/** Tabela de demandas: título, módulo, status, dono e última atividade. */
export default function StatusTable({ demands, selectedId, onSelect }: Props): React.ReactNode {
  if (demands.length === 0) {
    return <p className={styles.empty}>Nenhuma demanda encontrada.</p>;
  }

  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th>Título</th>
          <th>Módulo</th>
          <th>Status</th>
          <th>Dono</th>
          <th>Última atividade</th>
        </tr>
      </thead>
      <tbody>
        {demands.map((demand) => (
          <tr
            key={demand.id}
            className={clsx(styles.row, demand.id === selectedId && styles.rowSelected)}
            onClick={() => onSelect(demand.id)}
          >
            <td>{demand.title}</td>
            <td>{demand.module}</td>
            <td>
              <span className={styles.badge}>{demand.status}</span>
            </td>
            <td>{demand.owner}</td>
            <td>{demand.updated_at ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
