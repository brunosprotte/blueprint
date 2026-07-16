---
type: Skill
title: "SK-004 — OKF Consumption"
description: "Skill que ensina agentes a consumir bundles OKF v0.1: validar conformanca, navegar conceitos, auditar links, gerar relatorios."
tags: [okf-consumer, SKILL, okf, documentation]
timestamp: "2026-07-04T12:00:00Z"
generatedBy: SK-004
---

# SK-004 — OKF Consumption

> **Blueprint Skill**

| Campo             | Valor                             |
| ----------------- | --------------------------------- |
| **ID**            | SK-004                            |
| **Título**        | OKF Consumption                   |
| **Versão**        | 1.0.0                             |
| **Status**        | Approved                          |
| **Owner**         | Blueprint Engineering             |
| **Runtime State** | READING                           |
| **Entrada**       | Bundle OKF v0.1 (path)            |
| **Saída**         | Resumo, validacao, relatorio      |
| **Consumido por** | Agentes Leitores, Validadores, CI |
| **Spec Alvo**     | OKF v0.1                          |

---

# 1. Purpose

Ler bundles OKF v0.1 e extrair conhecimento navegavel.

Irma de SK-003 (que **gera**). Esta Skill **le**.

---

# 2. Core Principle

Bundle ja e conhecimento estruturado. Consumir = navegar, nao reinterpretar.

Use a tool canonica: `tools/okf-consumer.py`. Nao escreva parser custom.

---

# 3. Runtime Position

```text
Bundle OKF v0.1
      |
      v
  SK-004 (esta skill)
      |
      +---> validate (CI gate)
      +---> list / report (navegacao)
      +---> broken-links (auditoria)
```

Estado: **READING**. Le, nao escreve. Nao altera bundle. Nao inventa.

---

# 4. Agent Role

Atue como **Bundle Reader**.

Voce:

- recebe path do bundle;
- invoca `tools/okf-consumer.py` para operacoes estruturadas;
- interpreta resultados para o usuario;
- sinaliza problemas (conformance, links quebrados).

Voce nunca:

- modifica o bundle (use SK-003 para isso);
- re-escreve parser (use a tool);
- inventa conteudo ausente.

---

# 5. Inputs

| Campo         | Descricao                                    | Obrigatorio         |
| ------------- | -------------------------------------------- | ------------------- |
| `bundle_path` | Diretorio raiz do bundle OKF                 | Sim                 |
| `intent`      | `validate` / `navigate` / `audit` / `report` | Sim                 |
| `audience`    | `human` / `agent` / `both`                   | Nao (default: both) |

---

# 6. Outputs

Resposta do agente:

- sumario do bundle (n conceitos, type distribution);
- resultado do intent;
- achados de conformance ou links (se houver).

---

# 7. Reading Workflow

```text
Locate Bundle
    |
    v
Run tool: validate
    |
    v
Run tool: list
    |
    v
(Selective) Run tool: broken-links
    |
    v
Synthesize Summary
    |
    v
Report
```

Nao pular `validate` — bundle nao-conforme = leitura suspeita.

---

# 8. Step 1 — Locate Bundle

Receber `bundle_path` explicito. Nunca inferir. Bundle pode estar em `docs/OKF/<name>/`, em repo externo, ou em subdir local.

Se path nao existe, parar e informar.

---

# 9. Step 2 — Validate

Executar:

```bash
python tools/okf-consumer.py <bundle_path> validate
```

Interpretar:

- exit 0 + "OK: N concept(s)" = bundle integra;
- exit 1 + lista de erros = bundle nao-conforme, relatar cada erro com file path.

Decidir se prosseguir. Bundle nao-conforme ainda pode ser lido (consumidores OKF sao permissivos), mas sinalizar ao usuario.

---

# 10. Step 3 — List

Executar:

```bash
python tools/okf-consumer.py <bundle_path> list
```

Retornar lista de conceitos com `type`, `title`, `description`, `tags`, `resource`.

Para `audience: human`, formatar com paths relativos e hierarquia visivel.

Para `audience: agent`, retornar JSON-like structure (path -> frontmatter).

---

# 11. Step 4 — Audit Links (opcional)

Executar:

```bash
python tools/okf-consumer.py <bundle_path> broken-links
```

Spec OKF §5.3 diz que links quebrados sao tolerados. Mas para bundles maduros, limpa-los e boa pratica.

Reportar lista se houver.

---

# 12. Step 5 — Synthesize

Compor resposta para o usuario:

- quantos conceitos;
- quais `type`s dominam;
- problemas de conformance (se houver);
- links quebrados (se houver);
- caminho para o(s) conceito(s) mais relevante(s) ao intent original.

Terseness: o usuario pediu leitura, nao ensaio. `caveman-ultra` se aplicavel.

---

# 13. AI Checklist

Antes de concluir:

- bundle foi localizado?
- validate foi rodado?
- list foi sintetizado?
- broken-links foi checado (se intent = audit)?
- a saida para o usuario responde ao intent original?
- nada foi inventado alem do que o bundle diz?

---

# 14. Success Criteria

Bundle foi consumido com sucesso quando:

- `validate` passou (ou falhas foram relatadas);
- usuario sabe quantos conceitos existem e de quais tipos;
- links quebrados estao mapeados (se intent = audit);
- nenhum conteudo foi inventado.

---

# 15. AI Interpretation

Concluir que:

- esta Skill **le** — nao escreve;
- use a tool canonica, nao parser custom;
- bundle nao-conforme ainda e legivel, mas sinalize;
- links quebrados sao tolerados pela spec, mas uteis de limpar;
- estado do Runtime e **READING** — output e sumario, nao mutacao.

---

# 16. References

Tool:

- `tools/okf-consumer.py` (RI-002)

Docs:

- RI-002 — OKF Bundle Consumer
- SK-003 — OKF Cataloging (geracao)
- OKF v0.1 spec

Irmas:

- SK-001 — Business Discovery
- SK-002 — Technical Planning
