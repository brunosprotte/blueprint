import React, { useState } from 'react';
import clsx from 'clsx';
import styles from './styles.module.css';

type Props = {
  artifactId: string;
  disabled?: boolean;
  onApproved?: () => void;
};

type Outcome = {
  kind: 'ok' | 'error';
  message: string;
  /** 401 — mostra o link de login. */
  needsLogin?: boolean;
};

/**
 * Botão de aprovação de artefato — a única escrita do painel.
 *
 * `POST /api/artifacts/{id}/approve` dispara o pipeline de revisão da F6.
 * O painel **mostra**, não decide: a aprovação só sai de um clique humano
 * (design master §15.2).
 */
export default function ApproveButton({
  artifactId,
  disabled = false,
  onApproved
}: Props): React.ReactNode {
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  const approve = async () => {
    if (typeof window === 'undefined') return;
    const confirmed = window.confirm(
      `Aprovar o artefato ${artifactId}? O pipeline de revisão vai rodar no servidor.`
    );
    if (!confirmed) return;

    setBusy(true);
    setOutcome(null);
    try {
      const response = await fetch(
        `/api/artifacts/${encodeURIComponent(artifactId)}/approve`,
        {
          method: 'POST',
          credentials: 'same-origin',
          headers: { Accept: 'application/json' }
        }
      );

      if (response.status === 200 || response.status === 204) {
        setOutcome({ kind: 'ok', message: 'Pipeline disparado.' });
        onApproved?.();
        return;
      }

      const body = await response.json().catch(() => null);
      const error = body?.error ?? null;
      const message = String(error?.message ?? error?.code ?? `HTTP ${response.status}`);

      if (response.status === 409) {
        setOutcome({ kind: 'error', message: `Transição ilegal: ${message}` });
      } else if (response.status === 503) {
        setOutcome({
          kind: 'error',
          message: 'LLM indisponível, tente de novo depois.'
        });
      } else if (response.status === 401) {
        setOutcome({ kind: 'error', message: 'Faça login para aprovar.', needsLogin: true });
      } else {
        setOutcome({ kind: 'error', message });
      }
    } catch {
      setOutcome({ kind: 'error', message: 'Servidor indisponível.' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className={styles.approve}>
      <button
        type="button"
        className={clsx(styles.approveButton)}
        onClick={approve}
        disabled={busy || disabled}
      >
        {busy ? 'Aprovando…' : `Aprovar ${artifactId}`}
      </button>
      {outcome ? (
        <span
          className={clsx(
            outcome.kind === 'ok' ? styles.approveOk : styles.approveError
          )}
        >
          {outcome.message}
          {outcome.needsLogin ? (
            <>
              {' '}
              <a href="/api/auth/github">Entrar com GitHub</a>
            </>
          ) : null}
        </span>
      ) : null}
    </span>
  );
}
