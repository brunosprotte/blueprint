---
type: ReferenceImplementation
title: "RI-002 — OKF Bundle Consumer"
description: "CLI Python que consome bundles OKF v0.1: valida conformanca, lista conceitos, gera relatorio markdown, detecta links quebrados."
tags: [RI-002_OKF_BUNDLE_CONSUMER, okf, tooling]
timestamp: "2026-07-04T12:00:00Z"
generatedBy: RI-002
---

# RI-002 — OKF Bundle Consumer

> **Reference Implementation**

| Campo         | Valor                   |
| ------------- | ----------------------- |
| **ID**        | RI-002                  |
| **Título**    | OKF Bundle Consumer     |
| **Versão**    | 1.0.0                   |
| **Status**    | Approved                |
| **Owner**     | Blueprint Engineering   |
| **Linguagem** | Python 3.11+            |
| **Spec Alvo** | OKF v0.1                |
| **Artifact**  | `tools/okf-consumer.py` |

---

# 1. Purpose

CLI que **le** bundles OKF v0.1.

Complementa SK-003 (que **gera** bundles). Permite que humanos e agentes naveguem, validem e auditem bundles sem tooling custom.

Spec: <https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md>

---

# 2. Quick Start

```bash
# Validar conformanca OKF v0.1 §9
python tools/okf-consumer.py <bundle-path> validate

# Listar conceitos com metadata
python tools/okf-consumer.py <bundle-path> list

# Gerar relatorio markdown (stdout)
python tools/okf-consumer.py <bundle-path> report

# Detectar cross-links quebrados
python tools/okf-consumer.py <bundle-path> broken-links
```

Exit code `0` = sucesso. `1` = encontrou problemas. `2` = erro de uso.

---

# 3. Sub-commands

## 3.1 `validate`

Executa os 3 checks de conformanca da §9 da spec.

1. todo `*.md` nao-reservado tem frontmatter YAML parseavel;
2. todo frontmatter tem `type` nao-vazio;
3. `index.md` e `log.md` (quando presentes) nao tem frontmatter.

Output: lista de erros + count. Exit 1 se qualquer erro.

## 3.2 `list`

Lista cada conceito do bundle com seus campos principais: `type`, `title`, `description`, `tags`, `resource`.

Ordem alfabetica por path relativo.

## 3.3 `report`

Gera relatorio markdown completo. Inclui:

- metadata do bundle (nome, geracao, contagem);
- distribuicao por `type`;
- secao por conceito com todos os campos do frontmatter.

Util para PR descriptions, documentacao, ou revisao por stakeholders.

## 3.4 `broken-links`

Detecta links internos quebrados (`[text](./path.md)` ou `[text](/path.md)`).

Links externos (`http://`, `https://`, `mailto:`, `#anchor`) sao ignorados.

Broken links sao tolerados pela spec OKF §5.3 — mas este comando ajuda a limpa-los.

---

# 4. Dependencies

- Python 3.11+
- PyYAML 6.x

PyYAML ja e dependencia do projeto. Sem deps novas.

---

# 5. Architecture

```text
Bundle Path
    |
    v
rglob *.md  ──── filter reserved (index.md, log.md)
    |
    v
load_concept: parse frontmatter (yaml.safe_load)
    |
    v
sub-command handler (validate | list | report | broken-links)
    |
    v
stdout + exit code
```

Sem cache. Sem IO paralelo. Sem rede. Stdlib-first.

---

# 6. Output Conventions

Cada sub-command imprime em stdout. Nada em stderr exceto erros de uso.

Codigo de saida:

| Code | Significado                                |
| ---- | ------------------------------------------ |
| 0    | Sucesso / sem problemas                    |
| 1    | Comando encontrou problemas (relatar)      |
| 2    | Erro de uso (path invalido, args faltando) |

---

# 7. Example Session

```bash
$ python tools/okf-consumer.py docs/OKF/identity validate
OK: 12 concept(s), all conformant to OKF v0.1 §9

$ python tools/okf-consumer.py docs/OKF/identity list
* access-control.md
  type: Playbook
  title: Access Control
  description: Rules governing role-based access in the identity bundle.
  tags: access, security

* groups.md
  type: Concept
  title: Groups
  description: Collection of users sharing permissions.

$ python tools/okf-consumer.py docs/OKF/identity broken-links
OK: no broken internal links
```

---

# 8. Integration with Blueprint

| Agente        | Uso                                     |
| ------------- | --------------------------------------- |
| Modeladores   | `validate` apos gerar bundle via SK-003 |
| Validadores   | `validate` + `broken-links` em revisao  |
| Leitores      | `list` / `report` para navegar          |
| CI / pipeline | `validate` em pre-commit ou pre-PR      |

Skill complementar: SK-004 — OKF Consumption (`docs/SK/okf-consumer/SKILL.md`).

---

# 9. Limitations

- Nao renderiza Mermaid / diagrams.
- Nao resolve redirecionamentos.
- Nao detecta duplicacao de `id` entre conceitos.
- Nao segue links externos.
- Report nao tem theming (texto plano).

YAGNI. Cada limitacao pode ser enderecada quando o caso de uso surgir.

---

# 10. Self-Test

Criar bundle temporario e rodar os 4 sub-commands. Veja `tools/okf-consumer.py` para implementacao.

Fixture minima: 2 conceitos validos, 1 sem `type`, 1 link broken.

---

# 11. References

- OKF v0.1 — `GoogleCloudPlatform/knowledge-catalog/okf/SPEC.md`
- SK-003 — OKF Cataloging (`docs/SK/okf-catalog/SKILL.md`)
- SK-004 — OKF Consumption (`docs/SK/okf-consumer/SKILL.md`)
