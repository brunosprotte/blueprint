---
type: Skill
title: "SK-003 — OKF Cataloging"
description: "Catalog knowledge from any source into an OKF v0.1 conformant bundle. Directory of markdown with YAML frontmatter, human-readable, agent-parseable, git-diffable."
tags: [okf-catalog, SKILL, documentation, knowledge-management]
timestamp: "2026-07-04T12:00:00Z"
generatedBy: SK-003
---

# SK-003 — OKF Cataloging

> **Blueprint Skill**

| Campo             | Valor                                                                      |
| ----------------- | -------------------------------------------------------------------------- |
| **ID**            | SK-003                                                                     |
| **Título**        | OKF Cataloging                                                             |
| **Versão**        | 1.0.0                                                                      |
| **Status**        | Approved                                                                   |
| **Owner**         | Blueprint Architecture                                                     |
| **Runtime State** | MODELING                                                                   |
| **Entrada**       | Fonte de conhecimento + alvo do bundle                                     |
| **Saída**         | Bundle OKF v0.1 conformeante                                               |
| **Consumido por** | SK-001 (Business Discovery), SK-002 (Technical Planning), Agentes Leitores |
| **Spec Alvo**     | OKF v0.1 — `GoogleCloudPlatform/knowledge-catalog`                         |

---

# 1. Purpose

Catalogar conhecimento em um **bundle OKF v0.1**.

OKF = Open Knowledge Format. Diretório de markdown com frontmatter YAML. Legível por humano. Parseável por agente. Diffável em git.

Esta Skill não inventa. Apenas organiza o que já existe.

---

# 2. Core Principle

Bundle é **view**, não fonte autoritativa.

Fonte da verdade permanece onde nasceu (BR, SPEC, código, ADR, leitura). O bundle é referência navegável — link para fonte, não cópia.

Duplicação autoritativa é violação de conformance.

---

# 3. Runtime Position

```text
BR / SPEC / código / ADR / leitura
            |
            v
      SK-003 (esta skill)
            |
            v
     Bundle OKF v0.1
            |
            v
   Consumido por agentes de leitura
            |
            v
   Volta à fonte via cross-link
```

Estado: **MODELING**. Não implementa. Não escolhe tecnologia. Não altera fonte.

---

# 4. Agent Role

Atue como **Knowledge Curator**.

Você:

- lê a fonte inteira;
- identifica conceitos (entidades, decisões, processos, assets);
- atribui `type` por conceito;
- estrutura diretórios por afinidade;
- gera documentos concisos com cross-links;
- mantém o bundle conforme.

Você nunca:

- inventa fato;
- duplica conteúdo autoritativo (use link);
- escreve código;
- altera fonte original.

---

# 5. Inputs

| Campo           | Descrição                                            | Obrigatório |
| --------------- | ---------------------------------------------------- | ----------- |
| `source`        | BR, SPEC, código, ADR, texto livre, bundle existente | Sim         |
| `bundle_path`   | Raiz do bundle. Ex.: `docs/OKF/<bundle-name>`        | Sim         |
| `okf_version`   | Versão OKF alvo. Default: `0.1`                      | Não         |
| `type_taxonomy` | Vocabulário controlado de `type`. Default: livre     | Não         |
| `audience`      | `human`, `agent`, `both`. Default: `both`            | Não         |

---

# 6. Outputs

Bundle conforme OKF v0.1:

- 1+ conceitos como `*.md` com frontmatter válido;
- `index.md` por diretório (progressive disclosure);
- `log.md` na raiz (histórico);
- cross-links absolutos (preferenciais);
- `# Citations` em conceitos com claims externas.

---

# 7. Cataloging Workflow

```text
Load Source
    |
    v
Classify Concepts
    |
    v
Design Bundle Tree
    |
    v
Generate Concept Documents
    |
    v
Add Cross-Links
    |
    v
Generate Index Files
    |
    v
Generate Log File
    |
    v
Add Citations
    |
    v
Validate Conformance
    |
    v
Persist Bundle
    |
    v
Persist Doubts
```

Não pular etapas. Cada uma produz artefato verificável.

---

# 8. Step 1 — Load Source

Carregar fonte inteira. Listar se múltipla.

Nunca catalogar sobre fonte parcial. Cobertura parcial = bundle inválido.

---

# 9. Step 2 — Classify Concepts

Por conceito, definir:

- `id` (slug único no bundle);
- `type` (`Business Rule`, `SPEC`, `Table`, `API`, `Playbook`, `Decision`, `Concept`, ...);
- `title` (humano-legível);
- `description` (1 linha);
- `resource` (URI canônico, opcional);
- `tags` (lista, opcional);
- `timestamp` (ISO 8601, opcional).

Conceito que não cabe em 1 página → decompor.

---

# 10. Step 3 — Design Bundle Tree

Organizar conceitos em diretórios por afinidade.

Regras:

- diretório = grupo semântico, não categoria rígida;
- profundidade ≤ 4 (raiz + 3);
- conceitos pequenos podem ficar na raiz.

---

# 11. Step 4 — Generate Concept Document

Template obrigatório.

```markdown
---
type: <Type>
title: <Title>
description: <one-line summary>
resource: <optional canonical URI>
tags: [<tag>, <tag>]
timestamp: <ISO 8601>
---

# <Title>

<Body. Conteúdo relevante, sem fluff.>

# Citations

[1] <link externo ou referência interna>
```

Sem frontmatter → conceito inválido (§16).

---

# 12. Step 5 — Cross-Links

Forma preferencial: **absoluta relativa ao bundle**.

```markdown
Ver [tabela de pedidos](/tables/orders.md).
```

Estável quando o conceito se move dentro do subdiretório.

Forma aceitável: **relativa markdown**.

```markdown
Ver [vizinho](./other.md).
```

Link é _asserção de relação_. Tipo da relação fica no texto, não no link.

Tolerar link quebrado — alvo pode não existir ainda. Frontmatter ausente não.

---

# 13. Step 6 — Index Files

Gerar `index.md` em cada diretório. **Sem frontmatter.**

```markdown
# <Group Heading>

- [Title 1](path/to/concept-1.md) - description from frontmatter
- [Title 2](path/to/concept-2.md) - description from frontmatter

# Subgroup

- [Subdirectory](subdir/) - short description
```

`index.md` é listing. Sem corpo longo. Cada entry inclui a `description` do frontmatter do alvo.

---

# 14. Step 7 — Log File

Gerar `log.md` na raiz do bundle. Opcional em subdiretórios. **Sem frontmatter.**

```markdown
# Bundle Update Log

## 2026-07-04

- **Creation**: Bundle inicial com N conceitos de <fonte>.
- **Update**: Adicionado [novo conceito](/path/to/concept.md).
```

Entries datadas em ISO 8601 (`YYYY-MM-DD`). Newest first.

---

# 15. Step 8 — Citations

Se o body cita fonte externa, adicionar `# Citations` ao final do conceito.

```markdown
# Citations

[1] [BigQuery public dataset](https://cloud.google.com/...)
[2] [Internal runbook](https://wiki.acme.internal/...)
```

Numeração sequencial. URLs absolutas permitidas.

Claims sem citation em conceito que depende de fonte externa → marcar como dúvida (META-006).

---

# 16. Step 9 — Conformance Validation

Bundle é conforme OKF v0.1 quando **todas** as condições passam.

1. todo `*.md` não-reservado tem frontmatter YAML parseável;
2. todo frontmatter tem `type` não-vazio;
3. `index.md` e `log.md` (quando presentes) seguem §13/§14.

Falha em qualquer → corrigir antes de persistir. Re-executar até passar.

---

# 17. Reserved Filenames

| Filename     | Regra                              |
| ------------ | ---------------------------------- |
| `index.md`   | Listing. Sem frontmatter.          |
| `log.md`     | Histórico datado. Sem frontmatter. |
| outros `.md` | Conceito. Com frontmatter.         |

Conceito nunca usa nome reservado. Conflito → renomear conceito, não reserved.

---

# 18. Workspace Path

Default: `docs/OKF/<bundle-name>/`

Why: bundle OKF é **view** sobre BR/SPEC/ES, não pertence a essas categorias. Hospedar fora evita acoplamento categorial.

Criação de `docs/OKF/` como categoria oficial requer ADR (META-004 §11). Até lá, o path é convenção operacional, não contrato arquitetural.

---

# 19. AI Checklist

Antes de concluir:

- toda fonte foi carregada?
- cada conceito tem `type`?
- cross-links usam forma absoluta?
- `index.md` cobre o diretório?
- `log.md` registra a criação?
- claims externas têm `# Citations`?
- 3 checks de conformidade passam?
- dúvidas pendentes registradas (META-006)?

---

# 20. Success Criteria

Bundle está pronto quando:

- conforma OKF v0.1 (§16);
- navegável por humano sem abrir arquivos individuais;
- parseável por agente sem tooling custom;
- cross-links estáveis quando conceitos se movem no bundle;
- `log.md` reflete a história.

---

# 21. AI Interpretation

Concluir que:

- esta Skill é **view**, não fonte autoritativa;
- invenção de fato é violação de conformance;
- links quebrados tolerados, frontmatter ausente não;
- bundle vive sob `docs/OKF/` por convenção até ADR;
- estado do Runtime é **MODELING** — não escreva código.

---

# 22. References

Spec externa:

- `GoogleCloudPlatform/knowledge-catalog` — `okf/SPEC.md` (OKF v0.1)

Blueprint:

- META-001 — Knowledge Resolution Engine
- META-003 — Runtime Execution Model
- META-004 — Workspace Convention
- META-006 — Doubts Index Synchronization Flow

Irmãs:

- SK-001 — Business Discovery
- SK-002 — Technical Planning
