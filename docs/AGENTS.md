# AGENTS.md

> Bootstrap do Blueprint

Este repositório utiliza a metodologia **Blueprint**, baseada em **Knowledge Driven Engineering**.

O objetivo dos agentes não é escrever código rapidamente.

O objetivo é transformar conhecimento em software.

> **O código deve ser uma consequência do conhecimento.**

# Optmizing

Carregue as skills [docs\SK\caveman\SKILL.md] no modo Ultra e [docs\SK\ponytail\SKILL.md] no modo Ultra

---

# Core Principles

Todo agente deve respeitar os seguintes princípios.

- Nunca assumir informações.
- Toda decisão deve possuir origem rastreável.
- O conhecimento precede a implementação.
- O código é consequência da especificação.
- Implementações nunca alteram requisitos de negócio.

---

# Runtime Model

Toda execução deve seguir o fluxo definido em:

```
META-003 — Runtime Execution Model
```

Fluxo esperado.

```text
Discover

↓

Model

↓

Specify

↓

Resolve

↓

Implement

↓

Validate
```

Nunca misturar etapas.

---

# Workspace Convention

Toda saída deve respeitar:

```
META-004 — Workspace Convention
```

Estrutura oficial.

```text
docs/

├── BR/
├── SPEC/
├── ES/
├── PAT/
├── LS/
├── TS/
├── TP/
├── RI/
├── META/
└── SK/
```

Nenhum documento deve ser criado fora desta estrutura.

---

# Progressive Knowledge Loading

Carregar apenas o conhecimento necessário para a tarefa.

## Descoberta de Requisitos

Carregar.

```
docs\SK\business-discovery\SKILL.md
```

---

## Planejamento Técnico

Carregar.

```
docs\SK\technical-planning\SKILL.md
```

---

## Engenharia

Carregar.

```
ES-000 até ES-011 (docs/ES/)
```

Somente quando a tarefa envolver arquitetura ou especificação.

---

## Patterns

Carregar apenas quando necessários.

```
PAT-001 (docs/PAT/)
```

---

## Language Standards

Carregar apenas para organização do projeto.

```
LS-001 (docs/LS/)
```

---

## Technology Standards

Carregar somente quando existir implementação.

```
TS-001
TS-002
TS-003
TS-004
TS-005
TS-006
TS-007
```

(docs/TS)

---

## Technology Packs

Quando uma SPEC definir um Technology Pack.

Carregar.

```
TP-001 (docs/TP)
```

Todos os TS pertencentes ao Pack tornam-se automaticamente disponíveis.

---

## Reference Implementations

Carregar apenas quando uma SPEC solicitar.

```
RI-XXX (docs/RI)
```

Nunca utilizar Reference Implementations como documentação arquitetural.

---

# Business Discovery

Quando o usuário fornecer uma necessidade informal.

Executar.

```
SK-001 (docs\SK\business-discovery\SKILL.md)
```

Resultado esperado.

```text
docs/BR/<module>/<feature>.md
```

A Business Rule deve conter.

- contexto;
- atores;
- capacidades;
- regras;
- cenários;
- Acceptance Criteria;
- dúvidas pendentes.

Nunca produzir código nesta etapa.

---

# Technical Planning

Quando existir uma Business Rule aprovada.

Executar.

```
SK-002 (docs\SK\technical-planning\SKILL.md)
```

Resultado esperado.

- Specification Graph;
- uma ou mais Functional Specifications.

Toda Business Rule pode gerar múltiplas SPECs.

Exemplo.

```text
BR

↓

Frontend SPEC

↓

Backend SPEC

↓

API SPEC

↓

Persistence SPEC

↓

Testing SPEC
```

Cada SPEC deve possuir responsabilidade única.

---

# Specification Resolution

Toda SPEC deve identificar.

- Engineering Standards;
- Patterns;
- Language Standards;
- Technology Pack;
- Reference Implementations.

A resolução pertence ao META-001.

Nunca escolher tecnologias antes da resolução.

---

# Implementation

Implementações devem seguir exclusivamente as Functional Specifications.

Nunca:

- alterar Business Rules;
- alterar Acceptance Criteria;
- criar requisitos.

Toda implementação deve ser rastreável até uma SPEC.

---

# Validation

Toda implementação deve validar.

- Acceptance Criteria;
- Functional Specification;
- Engineering Standards;
- Testes.

Nenhuma funcionalidade é considerada concluída enquanto todos os Acceptance Criteria não estiverem atendidos.

---

# Acceptance Criteria

Acceptance Criteria representam a definição oficial de funcionamento de um requisito.

Eles devem orientar.

- implementação;
- testes unitários;
- testes de integração;
- testes End-to-End.

Todo Acceptance Criteria deve possuir implementação.

Nenhum Acceptance Criteria pode permanecer sem cobertura.

---

# Skills

| Skill                               | Responsabilidade                                  |
| ----------------------------------- | ------------------------------------------------- |
| docs\SK\business-discovery\SKILL.md | Descobrir e estruturar Business Rules             |
| docs\SK\technical-planning\SKILL.md | Planejar tecnicamente e gerar Specification Graph |

---

# Official Technology Pack

Para aplicações Next.js utilizar.

```
TP-001 (docs\TP)
```

Stack homologada.

- Next.js
- Prisma
- Zod
- React Hook Form
- shadcn/ui

---

# AI Checklist

Antes de iniciar qualquer tarefa verificar.

- Em qual estado do Runtime estou?
- Existe uma Business Rule?
- Existe uma SPEC?
- Os documentos necessários foram resolvidos?
- Estou alterando conhecimento ou apenas implementando?
- Todo comportamento possui origem rastreável?

Caso alguma resposta seja negativa.

Interromper a implementação e retornar à etapa anterior do Blueprint.
