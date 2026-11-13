#!/usr/bin/env node
/**
 * sync-method.mjs (F10) — espelha `docs/` do repo blueprint em `site/docs/metodo/`.
 *
 * Roda no `prebuild`. Regras (spec F10 §3.5):
 *  - `docs/` é somente leitura (invariante 4): o script nunca escreve na origem.
 *  - o destino é removido antes de copiar — nada obsoleto acumulado.
 *  - `docs/implementation-artifacts/` não é método: fica de fora da cópia.
 *  - link interno que não resolve na cópia é neutralizado (virando código inline);
 *    link absoluto que resolve é reescrito para caminho relativo.
 *  - autoverificação no fim: todo link interno que sobrou aponta para arquivo
 *    existente na cópia. Se não → stderr + exit 1 (o build quebra antes do Docusaurus).
 */
import { copyFile, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { existsSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SITE_DIR = path.resolve(HERE, '..');
const REPO_ROOT = path.resolve(SITE_DIR, '..');

const SRC_DIR = path.resolve(process.env.SDD_DOCS_DIR || path.join(REPO_ROOT, 'docs'));
const DEST_DIR = path.join(SITE_DIR, 'docs', 'metodo');

/** Diretórios da origem que não fazem parte do método. */
const EXCLUDED_DIRS = new Set([
  'implementation-artifacts',
  'node_modules',
  '.git',
  '.docusaurus',
  'build'
]);

/** `![alt](alvo)` ou `[texto](alvo "titulo")`. */
const LINK_RE = /(!?)\[([^\][]*)\]\(([^)\s]*)((?:\s+(?:"[^"]*"|'[^']*'))?)\)/g;

/** Link por referência: `[rotulo]: alvo`. */
const LINK_DEF_RE = /^([ \t]*)\[([^\]]+)\]:[ \t]*<?([^\s>]+)>?.*$/gm;

const stats = { copied: 0, rewritten: 0, neutralized: 0, external: 0, kept: 0 };

function toPosix(p) {
  return p.split(path.sep).join('/');
}

function isExternal(target) {
  return /^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(target);
}

function isFile(p) {
  try {
    return statSync(p).isFile();
  } catch {
    return false;
  }
}

/** Texto como código inline, com cerca que sobrevive a backtick dentro do texto. */
function inlineCode(text) {
  const runs = text.match(/`+/g) ?? [];
  const longest = runs.reduce((max, run) => Math.max(max, run.length), 0);
  if (longest === 0) return `\`${text}\``;
  const fence = '`'.repeat(longest + 1);
  const pad = text.startsWith('`') || text.endsWith('`') ? ' ' : '';
  return `${fence}${pad}${text}${pad}${fence}`;
}

function splitFragment(target) {
  const hash = target.indexOf('#');
  return hash === -1
    ? { pathPart: target, fragment: '' }
    : { pathPart: target.slice(0, hash), fragment: target.slice(hash) };
}

/**
 * Resolve o alvo de um link contra a cópia.
 * @returns {'external'|'anchor'|'file'|'missing'}
 */
function resolveLink(relFile, target) {
  if (!target) return 'anchor';
  if (isExternal(target)) return 'external';
  if (target.startsWith('#')) return 'anchor';
  const { pathPart } = splitFragment(target);
  if (!pathPart) return 'anchor';
  const candidate = pathPart.startsWith('/')
    ? path.join(DEST_DIR, pathPart.slice(1))
    : path.resolve(path.dirname(path.join(DEST_DIR, relFile)), pathPart);
  return isFile(candidate) ? 'file' : 'missing';
}

/** Reescreve os links markdown de um arquivo da cópia. */
function rewriteLinks(content, relFile) {
  return content.replace(LINK_RE, (full, bang, label, target, title) => {
    if (!target) return full;
    if (isExternal(target)) {
      stats.external += 1;
      return full;
    }
    if (target.startsWith('#')) return full;

    const { pathPart, fragment } = splitFragment(target);
    if (!pathPart) return full;

    const fileAbs = path.join(DEST_DIR, relFile);
    const candidate = pathPart.startsWith('/')
      ? path.join(DEST_DIR, pathPart.slice(1))
      : path.resolve(path.dirname(fileAbs), pathPart);

    if (!isFile(candidate)) {
      stats.neutralized += 1;
      const text = label.trim() || pathPart;
      return inlineCode(text);
    }

    if (pathPart.startsWith('/')) {
      const relative = toPosix(path.relative(path.dirname(fileAbs), candidate));
      stats.rewritten += 1;
      return `${bang}[${label}](${relative}${fragment}${title})`;
    }

    stats.kept += 1;
    return full;
  });
}

/** Reescreve definições de link por referência (`[rotulo]: alvo`). */
function rewriteLinkDefs(content, relFile) {
  return content.replace(LINK_DEF_RE, (full, indent, label, target) => {
    if (!target || isExternal(target) || target.startsWith('#')) return full;
    const { pathPart } = splitFragment(target);
    if (!pathPart) return full;
    const fileAbs = path.join(DEST_DIR, relFile);
    const candidate = pathPart.startsWith('/')
      ? path.join(DEST_DIR, pathPart.slice(1))
      : path.resolve(path.dirname(fileAbs), pathPart);
    if (!isFile(candidate)) {
      stats.neutralized += 1;
      return `${indent}[${label}]: ${inlineCode(pathPart)}`;
    }
    if (pathPart.startsWith('/')) {
      const relative = toPosix(path.relative(path.dirname(fileAbs), candidate));
      stats.rewritten += 1;
      return `${indent}[${label}]: ${relative}`;
    }
    stats.kept += 1;
    return full;
  });
}

async function walk(dir, base = '') {
  const out = [];
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const entry of entries) {
    if (entry.isDirectory()) {
      if (EXCLUDED_DIRS.has(entry.name)) continue;
      out.push(...(await walk(path.join(dir, entry.name), path.join(base, entry.name))));
    } else if (entry.isFile()) {
      out.push(path.join(base, entry.name));
    }
  }
  return out;
}

async function main() {
  if (!existsSync(SRC_DIR)) {
    process.stderr.write(`[sync] origem não encontrada: ${SRC_DIR}\n`);
    process.exit(1);
  }

  const files = await walk(SRC_DIR);
  if (files.length === 0) {
    process.stderr.write(`[sync] nenhum arquivo encontrado em ${SRC_DIR}\n`);
    process.exit(1);
  }

  await rm(DEST_DIR, { recursive: true, force: true });
  await mkdir(DEST_DIR, { recursive: true });

  // 1. copia tudo (a reescrita só pode rodar depois que os alvos existem)
  const relFiles = [];
  for (const rel of files) {
    const posixRel = toPosix(rel);
    const dest = path.join(DEST_DIR, rel);
    await mkdir(path.dirname(dest), { recursive: true });
    if (posixRel.toLowerCase().endsWith('.md')) {
      await writeFile(dest, await readFile(path.join(SRC_DIR, rel), 'utf8'), 'utf8');
    } else {
      await copyFile(path.join(SRC_DIR, rel), dest);
    }
    relFiles.push(posixRel);
    stats.copied += 1;
  }

  // 2. reescreve os links na cópia
  for (const rel of relFiles) {
    if (!rel.toLowerCase().endsWith('.md')) continue;
    const target = path.join(DEST_DIR, rel);
    const content = await readFile(target, 'utf8');
    const rewritten = rewriteLinkDefs(rewriteLinks(content, rel), rel);
    if (rewritten !== content) await writeFile(target, rewritten, 'utf8');
  }

  // 3. autoverificação: todo link interno remanescente resolve na cópia
  const broken = [];
  for (const rel of relFiles) {
    if (!rel.toLowerCase().endsWith('.md')) continue;
    const content = await readFile(path.join(DEST_DIR, rel), 'utf8');
    for (const match of content.matchAll(LINK_RE)) {
      const target = match[3];
      if (!target) continue;
      if (resolveLink(rel, target) === 'missing') broken.push(`${rel} -> ${target}`);
    }
    for (const match of content.matchAll(LINK_DEF_RE)) {
      const target = match[3];
      if (!target) continue;
      if (resolveLink(rel, target) === 'missing') broken.push(`${rel} -> ${target}`);
    }
  }

  if (broken.length > 0) {
    process.stderr.write(`[sync] ${broken.length} link(s) interno(s) sem destino na cópia:\n`);
    for (const item of broken) process.stderr.write(`  ${item}\n`);
    process.exit(1);
  }

  console.log(
    `[sync] ${stats.copied} arquivos copiados, ` +
      `${stats.rewritten} links reescritos, ` +
      `${stats.neutralized} links neutralizados`
  );
}

await main();
