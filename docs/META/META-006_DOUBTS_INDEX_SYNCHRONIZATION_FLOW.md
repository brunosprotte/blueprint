# META-006 — Doubts Index Synchronization Flow

> **Meta Document**

| Campo           | Valor                              |
| --------------- | ---------------------------------- |
| **ID**          | META-006                           |
| **Título**      | Doubts Index Synchronization Flow   |
| **Versão**      | 1.0.0                              |
| **Status**      | Approved                           |
| **Owner**       | Blueprint Architecture              |
| **Obrigatório** | Sim                                |
| **Aplica-se**   | BR, SPEC                           |

---

# 1. Purpose

Este documento define o fluxo oficial para manter os índices de dúvidas sincronizados quando uma BR ou SPEC é gerada, revisada ou aprovada.

O objetivo é garantir rastreabilidade imediata sem depender de ações manuais posteriores.

---

# 2. Core Principle

Todo artefato gerado deve nascer com vínculo explícito ao seu próprio arquivo de dúvidas.

O arquivo de dúvidas é a fonte de verdade da revisão daquele artefato.

Os índices centrais existem apenas como catálogo rápido de arquivos com pendências abertas.

---

# 3. Applicable Artifacts

## BR

- usa um arquivo proprio em `docs/implementation-artifacts/duvidas-br/<BR-id>.md`;
- registra rastreio de pendências de negócio;
- evolui com a BR.

## SPEC

- usa um arquivo proprio em `docs/implementation-artifacts/duvidas-spec/<SPEC-id>.md`;
- registra rastreio de pendências técnicas;
- evolui com a SPEC.

## Catalogs

- `docs/implementation-artifacts/duvidas-br.md` para localizar BRs com pendências abertas;
- `docs/implementation-artifacts/duvidas-spec.md` para localizar SPECs com pendências abertas.

---

# 4. Synchronization Workflow

Toda geração de BR ou SPEC deve seguir o fluxo abaixo.

```text
Generate Artifact
        ↓
Initialize Metadata
        ↓
Link Doubts Index
        ↓
Register Artifact Row
        ↓
Request User Approval
        ↓
User Review
        ↓
Agents Review
        ↓
Update Doubts Rows
        ↓
Request Final Approval
```

---

# 5. Initial Synchronization

Ao gerar o artefato, o agente deve:

1. preencher `doubtsIndex` no metadata com o arquivo proprio do artefato;
2. criar o arquivo de dúvidas do artefato com frontmatter espelhado;
3. registrar ou atualizar a pendência no arquivo proprio;
4. manter o vínculo rastreável pelo identificador do artefato;
5. atualizar o catálogo central apenas quando o artefato tiver pendências abertas.

---

# 6. Status Mapping

## BR

- `draft` -> arquivo proprio `draft`;
- `pending` -> arquivo proprio `pending`;
- `on user review` -> arquivo proprio `pending`;
- `on agents review` -> arquivo proprio `pending`;
- `approved` -> arquivo proprio `approved`.

## SPEC

- `draft` -> arquivo proprio `draft`;
- `pending` -> arquivo proprio `pending`;
- `on user review` -> arquivo proprio `pending`;
- `on agents review` -> arquivo proprio `pending`;
- `approved` -> arquivo proprio `approved`.

---

# 7. Review Synchronization

Quando o usuário aprovar o artefato e a revisão dos três agentes começar:

- registrar os achados no arquivo de dúvidas do próprio artefato;
- atualizar o status do arquivo de dúvidas;
- manter rastreabilidade entre achado, artefato e contexto;
- impedir avanço para `approved` enquanto existir item não `cleaned`.

---

# 8. Approval Gate

Somente quando todas as dúvidas do arquivo proprio estiverem `cleaned`, o agente pode solicitar ao usuário a troca de status para `approved`.

O usuário continua sendo a autoridade final para essa promoção.

---

# 9. File Rules

- `duvidas-br.md` recebe somente o catálogo de BRs com pendências abertas.
- `duvidas-spec.md` recebe somente o catálogo de SPECs com pendências abertas.
- cada arquivo de dúvidas proprio deve conter o identificador do artefato, status, pendência, origem e data de atualização.
- nenhum arquivo de dúvidas deve misturar BR e SPEC na mesma revisão.

---

# 10. AI Interpretation

Ao interpretar este documento, um agente deve concluir que:

- a sincronização de dúvidas faz parte da geração do artefato;
- BR e SPEC têm arquivos de dúvidas proprios;
- os catálogos centrais existem só para busca rápida de pendências abertas;
- `approved` depende de revisão concluída e confirmação do usuário;
- rastreabilidade é obrigatória desde a primeira escrita.

---

# 11. References

Complementa:

- META-004 — Workspace Convention
- META-005 — Validation Review Agents
