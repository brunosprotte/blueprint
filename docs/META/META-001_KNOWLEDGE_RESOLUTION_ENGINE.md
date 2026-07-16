---
type: Meta
title: "META-001 — Knowledge Resolution Engine"
description: Este documento define o algoritmo oficial utilizado para resolver conhecimento dentro do Blueprint.
tags: [META-001_KNOWLEDGE_RESOLUTION_ENGINE]
timestamp: "2026-07-04T11:34:11Z"
---

# META-001 — Knowledge Resolution Engine

> **Meta Document**

| Campo           | Valor                       |
| --------------- | --------------------------- |
| **ID**          | META-001                    |
| **Título**      | Knowledge Resolution Engine |
| **Versão**      | 1.0.0                       |
| **Status**      | Approved                    |
| **Owner**       | Blueprint Architecture      |
| **Obrigatório** | Sim                         |
| **Aplica-se**   | Todos os Agentes Blueprint  |

---

# 1. Purpose

Este documento define o algoritmo oficial utilizado para resolver conhecimento dentro do Blueprint.

O objetivo é permitir que agentes carreguem apenas os documentos necessários para responder uma solicitação.

A resolução deve minimizar contexto, evitar duplicação e preservar consistência arquitetural.

---

# 2. Core Principle

Nenhum agente deve carregar todo o Blueprint.

O agente deve resolver apenas o menor conjunto de documentos capaz de atender a solicitação.

---

# 3. Resolution Pipeline

Toda solicitação percorre a seguinte sequência lógica.

```text
User Request

↓

Problem Classification

↓

Knowledge Resolution

↓

Document Loading

↓

Validation

↓

Generation

↓

Review

↓

Response
```

Cada etapa possui responsabilidade exclusiva.

---

# 4. Step 1 — Problem Classification

O agente deve classificar a solicitação.

Categorias oficiais:

- Business
- Product
- Functional
- Architecture
- Pattern
- Language
- Technology
- Reference
- Decision
- Mixed

Caso exista mais de uma categoria, utilizar resolução incremental.

---

# 5. Step 2 — Resolve Required Categories

Após classificar a solicitação, determinar quais categorias são necessárias.

Exemplos:

### Nova regra de negócio

```text
BR
```

---

### Nova funcionalidade

```text
BR

↓

PRD

↓

SPEC
```

---

### Implementação

```text
SPEC

↓

ES

↓

PAT

↓

LS

↓

TS

↓

TP

↓

RI
```

---

### Correção tecnológica

```text
TS

↓

TP
```

---

### Ajuste arquitetural

```text
ES

↓

PAT
```

---

# 6. Step 3 — Resolve Dependencies

Cada documento pode depender apenas de categorias superiores.

```text
BR
↓
PRD
↓
SPEC
↓
ES
↓
PAT
↓
LS
↓
TS
↓
TP
↓
RI
```

Nunca resolver dependências em direção contrária.

---

# 7. Step 4 — Load Documents

Carregar apenas os documentos necessários.

Exemplo.

Solicitação:

> Implementar cadastro de alunos em Next.js.

Resolução:

```text
SPEC-001

↓

ES necessários

↓

PAT necessários

↓

LS-001

↓

TP-001

↓

RI-001
```

Não carregar documentos não utilizados.

---

# 8. Step 5 — Resolve Technology Pack

Caso exista Technology Pack compatível.

Carregar apenas o Pack.

Exemplo.

```text
TP-001

↓

TS-001

TS-002

TS-003

TS-004

TS-005
```

O agente nunca deve selecionar TS individualmente quando existir TP homologado.

---

# 9. Step 6 — Resolve Reference Implementations

Sempre procurar RI compatível.

Prioridade.

```text
Feature Match

↓

Technology Match

↓

Pattern Match

↓

Canonical Reference
```

Caso não exista RI específico.

Utilizar RI-001.

---

# 10. Step 7 — Validation

Antes da geração verificar.

- ES respeitados.
- PAT respeitados.
- LS respeitados.
- TS compatíveis.
- TP homologado.
- RI utilizado como referência.

Caso qualquer verificação falhe.

Interromper geração.

---

# 11. Step 8 — Generation

A geração ocorre obedecendo exatamente esta ordem.

```text
Contracts

↓

Domain

↓

Ports

↓

Use Cases

↓

Adapters

↓

Technology

↓

UI
```

Nunca inverter essa sequência.

---

# 12. Step 9 — Review

Antes da entrega verificar.

Arquitetura:

- dependências corretas;
- responsabilidades corretas;
- abstrações preservadas.

Tecnologia:

- TS respeitados.

Implementação:

- RI seguido.

---

# 13. Resolution Rules

O agente deve seguir obrigatoriamente:

- carregar o menor contexto possível;
- reutilizar conhecimento existente;
- evitar duplicação;
- preservar compatibilidade;
- respeitar a hierarquia do Blueprint.

---

# 14. Conflict Resolution

Quando dois documentos entrarem em conflito.

A prioridade será.

```text
META

↓

ADR

↓

ES

↓

PAT

↓

LS

↓

TS

↓

TP

↓

RI
```

Documentos inferiores nunca substituem superiores.

---

# 15. Missing Knowledge

Caso o conhecimento necessário não exista.

O agente deve.

1. identificar a categoria ausente;
2. sugerir criação do documento;
3. interromper geração caso a ausência comprometa a arquitetura.

Nunca inventar conhecimento estrutural.

---

# 16. AI Optimization

Para minimizar contexto.

O agente deve.

- carregar apenas documentos utilizados;
- reutilizar referências;
- evitar documentos redundantes;
- preferir Technology Packs;
- preferir Reference Implementations.

---

# 17. Example Resolution

Solicitação.

> Criar tela de cadastro de alunos utilizando Next.js.

Resolução.

```text
SPEC-001

↓

ES

↓

PAT

↓

LS-001

↓

TP-001

↓

RI-002
```

---

# 18. AI Interpretation

Ao interpretar este documento um agente deve concluir que:

- o Blueprint possui resolução determinística;
- documentos são carregados sob demanda;
- a geração sempre inicia pelos conceitos;
- implementações reutilizam Reference Implementations;
- conhecimento nunca deve ser inventado quando inexistente.

---

# 19. References

Complementa:

- META-000 — Blueprint Knowledge Model

É complementado por:

- META-002 — Generation Pipeline
- META-003 — Context Loading Strategy
- META-004 — Technology Resolution
- META-005 — Reference Resolution
