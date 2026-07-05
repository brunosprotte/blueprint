# SK-002 — Technical Planning

> **Blueprint Skill**

| Campo             | Valor                                           |
| ----------------- | ----------------------------------------------- |
| **ID**            | SK-002                                          |
| **Título**        | Technical Planning                              |
| **Versão**        | 2.0.0                                           |
| **Status**        | Approved                                        |
| **Owner**         | Blueprint Engineering                           |
| **Entrada**       | Business Rule (BR)                              |
| **Saída**         | Specification Graph + Functional Specifications |
| **Consumido por** | Agentes Implementadores                         |

---

# 1. Purpose

Esta Skill é responsável por transformar Business Rules em um conjunto de Functional Specifications implementáveis.

Ela não gera código.

Ela não escolhe tecnologias.

Ela não implementa software.

Seu objetivo é decompor uma necessidade de negócio em responsabilidades técnicas independentes.

Cada responsabilidade será representada por uma SPEC.

---

# 2. Core Principle

Uma Business Rule pode gerar uma ou mais Functional Specifications.

Cada SPEC deve possuir responsabilidade única.

As SPECs devem ser independentes sempre que possível.

O conjunto das SPECs forma o **Specification Graph** da funcionalidade.

---

# 3. Agent Role

Atue como um **Software Architect**.

Seu papel é transformar conhecimento de negócio em unidades técnicas coesas.

Você deve:

- analisar a Business Rule;
- validar Acceptance Criteria;
- identificar responsabilidades técnicas;
- agrupar responsabilidades relacionadas;
- criar o menor conjunto possível de SPECs;
- minimizar acoplamento entre SPECs;
- identificar dependências.

Nunca:

- implementar código;
- escolher frameworks;
- criar regras de negócio;
- modificar Business Rules.

---

# 4. Technical Planning Workflow

Toda execução deve seguir obrigatoriamente o fluxo abaixo.

```text
Load BR
        ↓
Validate BR
        ↓
Validate Acceptance Criteria
        ↓
Resolve Open Questions
        ↓
Identify Technical Responsibilities
        ↓
Build Specification Graph
        ↓
Generate Functional Specifications
        ↓
Validate Graph
        ↓
Persist Specifications
        ↓
Request User Approval
        ↓
User Review
        ↓
Agents Review
        ↓
Persist Doubts
        ↓
Final Approval
```

Ao concluir a SPEC, o agente deve solicitar aprovação explícita do usuário.

O fluxo de escrita da SPEC segue os estados:

```text
draft
↓
pending
↓
on user review
↓
on agents review
↓
approved
```

O agente deve:

- persistir a SPEC em `status: draft`;
- sincronizar o arquivo de dúvidas da SPEC conforme META-006;
- mover a SPEC para `status: pending` enquanto aguarda a revisão do usuário;
- mover a SPEC para `status: 'on user review'` quando o usuário iniciar a análise;
- após a aprovação do usuário, executar revisão por três agentes distintos;
- registrar as dúvidas encontradas no arquivo de dúvidas de SPEC;
- solicitar a troca para `approved` somente quando todas as dúvidas estiverem `cleaned`.

---

# 5. Validate Business Rule

Antes de iniciar o planejamento verificar.

- Business Rule aprovada.
- Acceptance Criteria completos.
- Não existem ambiguidades.
- Não existem Open Questions.

Caso contrário.

Retornar para SK-001.

---

# 6. Identify Technical Responsibilities

Analisar os Acceptance Criteria.

Identificar responsabilidades independentes.

Exemplos.

- Frontend
- Backend
- API
- Persistência
- Integrações
- Eventos
- Testes
- Relatórios

A quantidade depende exclusivamente da complexidade da Business Rule.

---

# 7. Specification Planning

Cada responsabilidade identificada deve originar uma SPEC.

Uma SPEC representa uma única unidade técnica.

Nunca misturar múltiplas responsabilidades na mesma SPEC.

---

# 8. Specification Graph

O primeiro artefato produzido pela Skill é o Specification Graph.

Exemplo.

```text
BR-001 Login

├── SPEC-001 Login Frontend
│
├── SPEC-002 Login API
│
├── SPEC-003 Login Backend
│
├── SPEC-004 Login Persistence
│
└── SPEC-005 Login Tests
```

O grafo representa todas as unidades necessárias para implementar a Business Rule.

---

# 9. Dependency Analysis

Após gerar o grafo identificar dependências.

Exemplo.

```text
Persistence

↓

Backend

↓

API

↓

Frontend

↓

Tests
```

Sempre minimizar dependências.

SPECs independentes devem poder ser implementadas em paralelo.

---

# 10. Functional Specification

Cada SPEC deve conter.

- Objetivo
- Escopo
- Responsabilidade
- Entradas
- Saídas
- Fluxo principal
- Fluxos alternativos
- Validações
- Failures
- Pré-condições
- Pós-condições
- Acceptance Criteria atendidos
- Dependências
- Blueprint Documents necessários

---

# 11. Blueprint Resolution

Para cada SPEC identificar.

Engineering Standards.

Patterns.

Language Standards.

Technology Pack.

Reference Implementations.

Nunca selecionar tecnologias diretamente.

A resolução pertence ao META-001.

---

# 12. Traceability

Toda SPEC deve possuir rastreabilidade.

```text
Acceptance Criteria

↓

SPEC

↓

Implementação

↓

Testes
```

Todo Acceptance Criteria deve estar presente em pelo menos uma SPEC.

---

# 13. Acceptance Criteria Mapping

Cada SPEC deve informar quais Acceptance Criteria implementa.

Exemplo.

```text
SPEC-001 Login Frontend

Atende.

AC-001

AC-002

AC-003

AC-004
```

Nenhum Acceptance Criteria pode permanecer sem implementação.

---

# 14. Workspace Convention

Toda SPEC deve ser salva conforme META-004.

Estrutura.

```text
docs/
└── SPEC/
    └── <modulo>/
```

Exemplo.

```text
docs/SPEC/login/

    login-frontend.md

    login-api.md

    login-backend.md

    login-persistence.md

    login-tests.md
```

---

# 15. Metadata

Toda SPEC deve iniciar com.

```yaml
---
id: SPEC-001
module: login
feature: login-frontend

createdBy: SK-002

createdFrom: BR-001

technologyPack: TP-001

status: draft
doubtsIndex: docs/implementation-artifacts/duvidas-spec/SPEC-001.md

version: 1.0.0
---
```

---

# 16. Approval and Review Flow

Quando a SPEC terminar de ser escrita, o agente deve:

1. apresentar a SPEC ao usuário;
2. solicitar aprovação explícita do usuário;
3. após a aprovação do usuário, executar três revisores independentes;
4. registrar as dúvidas e achados no índice de dúvidas de SPEC;
5. manter o documento em `on agents review` enquanto houver dúvida aberta;
6. solicitar a troca para `approved` somente quando todas as dúvidas estiverem `cleaned`.

Os três revisores obrigatórios são:

- Blind Hunter;
- Edge Case Hunter;
- Acceptance Auditor.

---

# 17. Specification Complexity

Cada SPEC deve receber uma classificação de complexidade.

Valores.

- LOW
- MEDIUM
- HIGH
- VERY HIGH

A complexidade serve apenas para planejamento.

Nunca representa esforço em horas.

---

# 18. AI Checklist

Antes de concluir verificar.

- A BR foi completamente compreendida?
- Todos os Acceptance Criteria foram mapeados?
- Existe apenas uma responsabilidade por SPEC?
- O acoplamento foi minimizado?
- Todas as dependências foram identificadas?
- O Specification Graph está consistente?
- Todas as SPECs seguem META-004?

---

# 19. Success Criteria

A Skill é considerada concluída quando.

- todos os Acceptance Criteria possuem implementação planejada;
- todas as SPECs possuem responsabilidade única;
- todas as dependências estão documentadas;
- o trabalho pode ser distribuído entre múltiplos implementadores sem ambiguidades.

---

# 20. AI Interpretation

Ao executar esta Skill o agente deve concluir que.

- Business Rules originam Specification Graphs.
- Cada SPEC representa uma única responsabilidade técnica.
- O objetivo não é minimizar a quantidade de documentos.
- O objetivo é maximizar coesão e minimizar acoplamento.
- SPECs independentes devem poder ser implementadas em paralelo.
- Nenhum Acceptance Criteria pode ficar sem cobertura.
- a sincronização de dúvidas de SPEC segue META-006;
- toda SPEC passa por revisão do usuário e por três agentes antes de ser aprovada;
- dúvidas de SPEC devem ser rastreadas em arquivo próprio.

---

# 21. Blueprint Integration

```text
docs/BR/<module>/<feature>.md
        │
        ▼
SK-002
Technical Planning
        │
        ▼
Specification Graph
        │
        ├── SPEC Frontend
        ├── SPEC Backend
        ├── SPEC API
        ├── SPEC Persistence
        ├── SPEC Tests
        ▼
docs/SPEC/<module>/
```
