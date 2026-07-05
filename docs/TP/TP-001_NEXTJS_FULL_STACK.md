# TP-001 — Next.js Full Stack

> **Technology Pack**

| Campo           | Valor                     |
| --------------- | ------------------------- |
| **ID**          | TP-001                    |
| **Título**      | Next.js Full Stack        |
| **Versão**      | 1.0.0                     |
| **Status**      | Stable                    |
| **Categoria**   | Blueprint Certified Stack |
| **Owner**       | Blueprint Engineering     |
| **Obrigatório** | Não                       |

---

# 1. Purpose

Este Technology Pack define uma stack oficialmente homologada para desenvolvimento de aplicações Full Stack utilizando o Blueprint.

Seu objetivo é eliminar decisões repetitivas de tecnologia e garantir que todas as implementações utilizem um conjunto consistente de ferramentas previamente validadas.

O Technology Pack não altera a arquitetura.

Ele apenas fornece implementações para os conceitos definidos pelo Blueprint.

---

# 2. Core Principle

O Technology Pack representa uma combinação certificada de tecnologias.

Ao selecionar um Technology Pack, todas as tecnologias, padrões e convenções já são consideradas compatíveis entre si.

O agente não deve selecionar tecnologias individualmente.

---

# 3. Certified Stack

| Tecnologia            | Responsabilidade       |
| --------------------- | ---------------------- |
| Next.js               | Runtime Full Stack     |
| React                 | Interface              |
| TypeScript            | Linguagem              |
| Prisma                | Persistência           |
| Zod                   | Validação Estrutural   |
| React Hook Form       | Estado dos Formulários |
| shadcn/ui             | Design System          |
| Tailwind CSS          | Layout e Tokens        |
| Vitest                | Testes Unitários       |
| React Testing Library | Testes Front-end       |

Todas as tecnologias acima foram homologadas para trabalhar em conjunto.

---

# 4. Implemented Technology Standards

Este Technology Pack implementa automaticamente.

| Documento                               |
| --------------------------------------- |
| TS-001 — Next.js Standard               |
| TS-002 — Prisma Persistence Standard    |
| TS-003 — Zod Validation Standard        |
| TS-004 — React Hook Form Standard       |
| TS-005 — Shadcn/UI Standard             |
| TS-006 — Backend Unit Testing Standard  |
| TS-007 — Frontend Unit Testing Standard |

O agente não deve resolver individualmente esses documentos.

---

# 5. Supported Language Standards

Este Technology Pack utiliza.

| Documento                             |
| ------------------------------------- |
| LS-001 — TypeScript Language Standard |

---

# 6. Supported Patterns

Este Technology Pack implementa.

| Pattern              | Implementação           |
| -------------------- | ----------------------- |
| Repository           | Prisma                  |
| Factory              | TypeScript              |
| Mapper               | TypeScript              |
| Composition Root     | Next.js                 |
| Stable UI Identifier | `data-testid` (PAT-001) |

Novos Patterns podem ser adicionados sem alterar este documento.

---

# 7. Supported Engineering Standards

Todos os Engineering Standards permanecem válidos.

Este Technology Pack apenas fornece implementações tecnológicas para os conceitos arquiteturais definidos pelos ES.

---

# 8. Capability Matrix

| Capability      | Status           |
| --------------- | ---------------- |
| CRUD            | ✅ Certified     |
| Authentication  | ✅ Certified     |
| Forms           | ✅ Certified     |
| Validation      | ✅ Certified     |
| Dashboards      | ✅ Certified     |
| Tables          | ✅ Certified     |
| File Upload     | 🟡 Partial       |
| Background Jobs | 🟡 Partial       |
| Event Driven    | 🟡 Partial       |
| Offline Sync    | ❌ Not Certified |

A matriz representa apenas o nível de homologação da stack.

---

# 9. Runtime Architecture

```text
Browser
        │
        ▼
React Components
        │
        ▼
Services
        │
        ▼
Next.js Route Handlers
        │
        ▼
Application
        │
        ▼
Output Ports
        │
        ▼
Prisma Adapters
        │
        ▼
Database
```

Cada camada mantém responsabilidade única.

---

# 10. Design System

O Design System oficial utiliza.

- shadcn/ui
- Tailwind CSS
- Design Tokens
- PAT-001 — Stable UI Identifier

Todos os componentes devem seguir TS-005.

---

# 11. Testing Strategy

Este Technology Pack adota três níveis de testes.

## Backend

TS-006

- Domain
- Application
- Mappers
- Services

---

## Front-end

TS-007

- Componentes
- Formulários
- Fluxos da interface

---

## End-to-End

Quando aplicável.

- Fluxos críticos
- Jornadas completas do usuário

A estratégia E2E poderá ser definida por um Technology Standard específico.

---

# 12. Blueprint Resolution

Quando uma SPEC utilizar TP-001, o agente deve carregar automaticamente.

```text
LS-001

↓

TS-001

↓

TS-002

↓

TS-003

↓

TS-004

↓

TS-005

↓

TS-006

↓

TS-007
```

Não é necessário resolver esses documentos individualmente.

---

# 13. Supported Skills

| Skill                       | Utilização |
| --------------------------- | ---------- |
| SK-001 — Business Discovery | Não        |
| SK-002 — Technical Planning | Sim        |
| Agentes Implementadores     | Sim        |
| Agentes Revisores           | Sim        |

---

# 14. Workspace Integration

Este Technology Pack não gera artefatos.

Ele é referenciado pelas Functional Specifications produzidas pela SK-002.

Exemplo.

```text
docs/SPEC/login/login-frontend.md
```

```yaml
technologyPack: TP-001
```

---

# 15. Lifecycle

Todo Technology Pack deve possuir um estado.

- Draft
- Experimental
- Stable
- Deprecated

Este documento encontra-se em estado **Stable**.

---

# 16. AI Checklist

Antes de utilizar TP-001 verificar.

- A linguagem é TypeScript?
- O projeto utiliza Next.js?
- Os TS obrigatórios estão disponíveis?
- Existe compatibilidade com a SPEC?
- Todos os Patterns necessários possuem implementação?

Caso alguma resposta seja negativa, selecionar outro Technology Pack.

---

# 17. AI Interpretation

Ao interpretar este documento, um agente deve concluir que.

- existe uma stack previamente homologada;
- todas as tecnologias já são compatíveis entre si;
- não é necessário escolher bibliotecas individualmente;
- o Technology Pack implementa os Technology Standards;
- a arquitetura continua sendo definida pelos Engineering Standards;
- as SPECs devem apenas referenciar o Technology Pack.

---

# 18. References

Este documento depende de.

- META-001 — Knowledge Resolution Engine
- META-003 — Runtime Execution Model
- META-004 — Workspace Convention

Implementa.

- LS-001
- TS-001
- TS-002
- TS-003
- TS-004
- TS-005
- TS-006
- TS-007

Utiliza.

- PAT-001 — Stable UI Identifier
