#!/usr/bin/env node
/**
 * gen-demandas.mjs (F10) — gera `site/docs/demandas/` a partir da API do servidor.
 *
 * Roda no `prebuild` (depois do `sync`). Regras (spec F10 §3.6):
 *  - sem `SDD_URL` o script sai com 0 e não gera dossiê (dev local sem servidor);
 *    o índice existe sempre, para a sidebar `demandas` não ficar vazia.
 *  - com `SDD_URL` definido e servidor fora → exit 1 (o CI não publica site
 *    com demandas desatualizadas).
 *  - auth por `SDD_TOKEN` (mesmo nome do kit, Contrato Comum §7.7); sem token,
 *    a requisição sai sem Authorization (sessão por cookie).
 *  - o destino é removido antes de escrever.
 *  - autoverificação: todo link escrito aponta para um arquivo escrito.
 */
import { mkdir, rm, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SITE_DIR = path.resolve(HERE, '..');
const DEST_DIR = path.join(SITE_DIR, 'docs', 'demandas');

const RAW_URL = process.env.SDD_URL;
const TOKEN = process.env.SDD_TOKEN;

/** `SDD_URL` pode vir sem `/api` — normaliza para a base da API. */
function apiBase(raw) {
  const trimmed = raw.replace(/\/+$/, '');
  return /\/api$/i.test(trimmed) ? trimmed : `${trimmed}/api`;
}

function headers() {
  const h = { Accept: 'application/json' };
  if (TOKEN) h.Authorization = `Bearer ${TOKEN}`;
  return h;
}

async function getJson(url) {
  let res;
  try {
    res = await fetch(url, { headers: headers(), credentials: 'omit' });
  } catch (cause) {
    const err = new Error(`GET ${url} falhou: ${cause?.message ?? cause}`);
    err.network = true;
    throw err;
  }
  const text = await res.text();
  let body = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }
  if (!res.ok) {
    const err = new Error(`GET ${url} -> ${res.status}`);
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body;
}

/** Parse tolerante da lista: array puro, `{demands: []}` ou `{items: []}`. */
function extractList(body) {
  if (Array.isArray(body)) return body;
  if (body && typeof body === 'object') {
    if (Array.isArray(body.demands)) return body.demands;
    if (Array.isArray(body.items)) return body.items;
  }
  return [];
}

/** YAML: string entre aspas duplas, com `\` e `"` escapados. */
function yamlString(value) {
  return `"${String(value ?? '').replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}

/** Scalar simples de YAML (sem aspas) ou string entre aspas. */
function yamlScalar(value) {
  const text = String(value ?? '');
  return /^[A-Za-z0-9._-]+$/.test(text) ? text : yamlString(text);
}

/** Célula de tabela: `|` escapado, quebras de linha viram espaço. */
function cell(value) {
  return String(value ?? '')
    .replace(/\r?\n/g, ' ')
    .replace(/\|/g, '\\|')
    .trim();
}

/** Conteúdo markdown de uma entrada de artefato (string ou objeto). */
function artifactContent(entry) {
  if (typeof entry === 'string') return entry;
  if (!entry || typeof entry !== 'object') return '';
  for (const key of ['content', 'markdown', 'body', 'summary']) {
    const value = entry[key];
    if (typeof value === 'string' && value.trim()) return value;
  }
  return '';
}

function artifactLabel(entry) {
  if (!entry || typeof entry !== 'object') return '';
  const id = entry.id ? String(entry.id) : '';
  const title = entry.title ? String(entry.title) : '';
  if (id && title) return `${id} — ${title}`;
  return id || title;
}

function renderArtifacts(entries) {
  if (!Array.isArray(entries) || entries.length === 0) return '_Nada registrado._\n';
  const blocks = [];
  for (const entry of entries) {
    const content = artifactContent(entry);
    const label = artifactLabel(entry);
    if (label) blocks.push(`#### ${label}\n\n${content.trim() || '_Sem conteúdo._'}`);
    else blocks.push(content.trim() || '_Sem conteúdo._');
  }
  return `${blocks.join('\n\n')}\n`;
}

function renderAcs(acs) {
  if (!Array.isArray(acs) || acs.length === 0) return '_Nenhum AC registrado._\n';
  const lines = acs.map((ac) => {
    if (typeof ac === 'string') return `- ${ac}`;
    const id = ac?.id ? String(ac.id) : '';
    const title = ac?.title ? String(ac.title) : '';
    if (id && title) return `- **${id}** — ${title}`;
    if (id) return `- **${id}**`;
    return `- ${title || '(sem título)'}`;
  });
  return `${lines.join('\n')}\n`;
}

function renderGraph(edges) {
  if (!Array.isArray(edges) || edges.length === 0) return '_Sem arestas._\n';
  const lines = edges.map((edge) => {
    if (typeof edge === 'string') return `- ${edge}`;
    const parent = edge?.parent ?? edge?.parent_id ?? edge?.from ?? '?';
    const child = edge?.child ?? edge?.child_id ?? edge?.to ?? '?';
    const type = edge?.type ?? 'depends_on';
    return `- ${parent} → ${child} (${type})`;
  });
  return `${lines.join('\n')}\n`;
}

function renderCommits(commits) {
  if (!Array.isArray(commits) || commits.length === 0) return '_Nenhum commit._\n';
  const rows = commits.map((commit) => {
    const sha = String(commit?.sha ?? '');
    const short = sha.slice(0, 7);
    const message = cell(commit?.message ?? '');
    const branch = cell(commit?.branch ?? '—');
    const date = cell(commit?.created_at ?? commit?.at ?? '—');
    return `| ${cell(short)} | ${message} | ${branch} | ${date} |`;
  });
  return ['| sha | mensagem | branch | data |', '| --- | --- | --- | --- |', ...rows].join('\n') + '\n';
}

function renderReviews(reviews) {
  if (!Array.isArray(reviews) || reviews.length === 0) return '_Nenhuma review._\n';
  const rows = reviews.map((review) => {
    const sha = String(review?.commit_sha ?? review?.sha ?? '');
    const verdict = cell(review?.verdict ?? '—');
    const findings = Array.isArray(review?.findings) ? review.findings.length : 0;
    return `| ${cell(sha.slice(0, 7) || '—')} | ${verdict} | ${findings} |`;
  });
  return ['| sha | veredito | achados |', '| --- | --- | --- |', ...rows].join('\n') + '\n';
}

function renderDesvios(desvios) {
  if (!Array.isArray(desvios) || desvios.length === 0) return '_Nenhum desvio._\n';
  const blocks = desvios.map((desvio) => {
    if (typeof desvio === 'string') return `- ${desvio}`;
    const ac = desvio?.ac ? String(desvio.ac) : '';
    const title = desvio?.title ? String(desvio.title) : '';
    const kind = desvio?.kind ? String(desvio.kind) : '';
    const detail = desvio?.detail ? String(desvio.detail) : '';
    const head = [ac && `**${ac}**`, title, kind && `(\`${kind}\`)`].filter(Boolean).join(' — ');
    return detail ? `- ${head}\n  ${detail}` : `- ${head}`;
  });
  return `${blocks.join('\n')}\n`;
}

function ownerOf(demand) {
  const owner = demand?.owner;
  if (owner && typeof owner === 'object') {
    return String(owner.login ?? owner.name ?? owner.id ?? '—');
  }
  if (typeof owner === 'string' && owner.trim()) return owner;
  if (demand?.claimed_by) return String(demand.claimed_by);
  return '—';
}

function repoOf(demand) {
  return String(demand?.repo ?? demand?.repo_id ?? '—');
}

function renderDemand(demand, dossier) {
  const id = String(demand?.id ?? '');
  const title = String(demand?.title ?? id);
  const module = String(demand?.module ?? '');
  const status = String(demand?.status ?? '');
  const owner = ownerOf(demand);
  const repo = repoOf(demand);
  const updatedAt = String(demand?.updated_at ?? '—');

  const necessidade = dossier?.necessidade ?? {};
  const proposta = dossier?.proposta ?? {};
  const implementacao = dossier?.implementacao ?? {};

  const tags = module ? `tags: [demanda, ${yamlScalar(module)}]` : 'tags: [demanda]';

  return `---
title: ${yamlString(title)}
description: ${yamlString(`Dossiê da demanda ${id}`)}
sidebar: false
${tags}
---

# Demanda: ${title}

| Campo | Valor |
| --- | --- |
| **ID** | ${cell(id)} |
| **Módulo** | ${cell(module)} |
| **Status** | ${cell(status)} |
| **Dono** | ${cell(owner)} |
| **Repositório** | ${cell(repo)} |
| **Atualizada em** | ${cell(updatedAt)}

## Necessidade

### BR

${renderArtifacts(necessidade.br)}
### Acceptance Criteria

${renderAcs(necessidade.acs)}
## Proposta

${renderArtifacts(proposta.specs)}
### Grafo

${renderGraph(proposta.grafo)}
## Implementação

### Commits

${renderCommits(implementacao.commits)}
### Reviews

${renderReviews(implementacao.reviews)}
## Desvios

${renderDesvios(dossier?.desvios)}`;
}

function renderIndex(entries) {
  // `slug: /demandas` fixa a rota do índice em `/docs/demandas` — é onde o navbar e
  // o footer apontam (spec F10 §3.3) e `onBrokenLinks: 'throw'` derruba o build
  // se essa rota não resolver. (`id` não serve: ele é relativo à pasta do arquivo
  // e produziria `/docs/demandas/demandas`.)
  const head = `---
slug: /demandas
title: Demandas
sidebar_label: Demandas
sidebar_position: 1
---

# Demandas
`;
  if (entries.length === 0) {
    return `${head}

Nenhuma demanda gerada.
`;
  }
  const lines = entries.map(({ id, demand }) => {
    const title = String(demand?.title ?? id);
    const module = String(demand?.module ?? '—');
    const status = String(demand?.status ?? '—');
    const updated = String(demand?.updated_at ?? '—').slice(0, 10);
    return `- [${title}](/docs/demandas/${id}) — ${module} — ${status} — ${updated}`;
  });
  return `${head}

${lines.join('\n')}
`;
}

async function main() {
  await rm(DEST_DIR, { recursive: true, force: true });
  await mkdir(DEST_DIR, { recursive: true });

  if (!RAW_URL) {
    await writeFile(path.join(DEST_DIR, 'indice.md'), renderIndex([]), 'utf8');
    console.log('[gen] SDD_URL ausente — nenhuma demanda gerada');
    return;
  }

  const base = apiBase(RAW_URL);
  let demands;
  try {
    demands = extractList(await getJson(`${base}/demands`));
  } catch (err) {
    process.stderr.write(`[gen] não consegui listar demandas em ${base}: ${err.message}\n`);
    process.exit(1);
  }

  const written = [];
  for (const demand of demands) {
    const id = demand?.id ? String(demand.id) : '';
    if (!id) continue;
    let dossier = null;
    try {
      dossier = await getJson(`${base}/knowledge/dossier/${encodeURIComponent(id)}`);
    } catch (err) {
      process.stderr.write(`[gen] dossiê da demanda ${id} falhou: ${err.message}\n`);
      process.exit(1);
    }
    await writeFile(path.join(DEST_DIR, `${id}.md`), renderDemand(demand, dossier), 'utf8');
    written.push({ id, demand });
  }

  const index = renderIndex(written);
  await writeFile(path.join(DEST_DIR, 'indice.md'), index, 'utf8');

  // Autoverificação: todo link do índice aponta para um arquivo escrito aqui
  // (o arquivo de cada demanda é `<id>.md`).
  const broken = [];
  for (const match of index.matchAll(/\]\((\/docs\/demandas\/[^)]+)\)/g)) {
    const target = match[1].replace('/docs/demandas/', '');
    if (!existsSync(path.join(DEST_DIR, `${target}.md`))) broken.push(target);
  }
  if (broken.length > 0) {
    process.stderr.write(`[gen] índice com ${broken.length} link(s) sem arquivo:\n`);
    for (const item of broken) process.stderr.write(`  ${item}\n`);
    process.exit(1);
  }

  console.log(`[gen] ${written.length} demanda(s) gerada(s) em docs/demandas/`);
}

await main();
