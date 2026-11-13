import React from 'react';
import Layout from '@theme/Layout';
import StatusPanel from '@site/src/components/StatusPanel';

/** Rotas consumidas pelo painel — todas same-origin, sem CORS (spec F10 §3.8). */
const ROTAS: [string, string, string][] = [
  ['GET', '/api/demands', 'lista as demandas; os filtros de status e repo são de cliente'],
  ['GET', '/api/demands/{id}', 'detalhe da demanda — artefatos em revisão'],
  ['GET', '/api/events/stream', 'SSE dos eventos; o painel guarda os últimos 200'],
  ['GET', '/api/events?demand=&since=', 'poll de 30 s, assume quando o SSE cai'],
  ['POST', '/api/artifacts/{id}/approve', 'única escrita: dispara o pipeline de revisão']
];

/** Ciclo de vida da demanda (design master §9.1 / Contrato Comum §7.1). */
const FLUXO: [string, string][] = [
  ['open', 'demanda criada na fila do repo (POST /api/demands)'],
  ['claimed', 'claim atômico com SKIP LOCKED (POST /api/claims)'],
  ['in_progress', 'POST /api/demands/{id}/start — só quem fez o claim'],
  ['review', 'commit reportado (POST /api/reviews)'],
  ['merged', 'review mais recente clean/suggestions (POST /api/demands/{id}/merge)'],
  ['done', 'POST /api/demands/{id}/close']
];

/**
 * Home do back-office.
 *
 * Sem lógica de dados no SSR: o painel só fala com a API dentro de `useEffect`,
 * então o build estático não quebra (spec F10 §3.7).
 */
export default function Home(): React.ReactNode {
  return (
    <Layout
      title="Painel de status"
      description="Ambiente Spec-Driven de multiagentes — acompanhe as demandas em andamento"
    >
      <main className="container margin-vert--lg">
        <h1>Blueprint SDD</h1>
        <p>
          Back-office do ambiente Spec-Driven de multiagentes. O painel{' '}
          <strong>mostra</strong> o que está acontecendo — a orquestração de fato
          acontece nos scripts do kit.
        </p>
        <StatusPanel />

        <section className="margin-vert--lg">
          <h2>Back-office</h2>
          <p>
            O site é <strong>estático</strong>: o espelho do método e os dossiês das
            demandas são gerados no build. O único componente vivo é o painel acima —
            ele mostra o estado do servidor e não decide nenhuma transição. A única
            escrita é a aprovação explícita de artefato, disparada por clique humano.
          </p>

          <h3>Rotas consumidas pelo painel</h3>
          <table>
            <thead>
              <tr>
                <th>Método</th>
                <th>Rota</th>
                <th>Uso</th>
              </tr>
            </thead>
            <tbody>
              {ROTAS.map(([methodo, rota, uso]) => (
                <tr key={rota}>
                  <td>
                    <code>{methodo}</code>
                  </td>
                  <td>
                    <code>{rota}</code>
                  </td>
                  <td>{uso}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>
            Os dossiês de cada demanda são gerados no build a partir de{' '}
            <code>GET /api/knowledge/dossier/&#123;demand_id&#125;</code> e publicados
            em <code>/docs/demandas/&#123;id&#125;</code>.
          </p>

          <h3>Fluxo da demanda</h3>
          <p>
            <code>open → claimed → in_progress → review → merged → done</code>. A
            qualquer estado a demanda pode ir para <code>blocked</code> com motivo;
            <code> release</code> devolve <code>claimed</code> para <code>open</code>.
          </p>
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>Gatilho</th>
              </tr>
            </thead>
            <tbody>
              {FLUXO.map(([status, gatilho]) => (
                <tr key={status}>
                  <td>
                    <code>{status}</code>
                  </td>
                  <td>{gatilho}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3>Aprovação de artefato</h3>
          <p>
            O artefato segue <code>draft → pending → on user review → on agents
            review → approved → stable</code>. O botão de aprovação dispara{' '}
            <code>POST /api/artifacts/&#123;id&#125;/approve</code>, que roda o pipeline
            no servidor: linter, Blind Hunter, Edge Case Hunter e Acceptance Auditor, em
            ordem fixa. Os achados viram dúvidas; só com o linter limpo e todas as
            dúvidas resolvidas o artefato vira <code>approved</code>. Pipeline
            indisponível devolve <code>503</code> — nada é bloqueado por indisponibilidade
            externa.
          </p>
        </section>
      </main>
    </Layout>
  );
}
