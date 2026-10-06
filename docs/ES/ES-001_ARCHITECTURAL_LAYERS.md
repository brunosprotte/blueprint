---
type: EngineeringStandard
title: "ES-001 — Architectural Layers"
description: "Como o Blueprint organiza responsabilidades arquiteturais para preservar independência entre conceitos e implementações?"
tags: [ES-001_ARCHITECTURAL_LAYERS]
timestamp: "2026-07-04T17:20:20Z"
---

# ES-001 — Architectural Layers

> **Engineering Standard**

| Campo           | Valor                 |
| --------------- | --------------------- |
| **ID**          | ES-001                |
| **Título**      | Architectural Layers  |
| **Versão**      | 1.0.0                 |
| **Status**      | Approved              |
| **Owner**       | Software Architecture |
| **Obrigatório** | Sim                   |
| **Aplica-se**   | Toda a Arquitetura    |

---

# 1. Architectural Question

Como o Blueprint organiza responsabilidades arquiteturais para preservar independência entre conceitos e implementações?

---

# 2. Purpose

Este documento define o modelo oficial de camadas arquiteturais do Blueprint.

Cada camada representa um nível de responsabilidade.

Camadas organizam conhecimento.

Não representam tecnologias, diretórios ou módulos físicos.

Sua finalidade é estabelecer limites claros entre responsabilidades arquiteturais.

---

# 3. Vocabulary

## Architectural Layer

Unidade responsável por agrupar conceitos com responsabilidades semelhantes.

---

## Dependency Direction

Sentido permitido para dependências entre camadas arquiteturais.

---

## Architectural Boundary

Limite que separa responsabilidades distintas.

---

## Architectural Isolation

Capacidade de uma camada evoluir sem alterar o significado das demais.

---

# 4. Architectural Entity

### Entity

Architectural Layer

---

### Responsibility

Organizar responsabilidades arquiteturais em níveis independentes.

---

### Architectural Owner

Software Architecture

---

### Known By

Todos os componentes arquiteturais.

---

### Represented By

Language Standards.

---

### Implemented Through

Technology Standards.

---

# 5. Architectural Layers

O Blueprint define quatro camadas arquiteturais.

## Domain

Representa o conhecimento do domínio.

Contém conceitos e regras fundamentais.

O domínio desconhece qualquer detalhe externo.

---

## Application

Representa a execução dos casos de uso.

Coordena o fluxo da aplicação.

Aplica regras de negócio utilizando o domínio.

---

## Adapters

Representam a comunicação entre a aplicação e elementos externos.

Traduzem conceitos arquiteturais para representações específicas.

---

## Infrastructure

Representa recursos externos utilizados pela aplicação.

Fornece implementações concretas para necessidades arquiteturais.

---

# 6. Layer Responsibilities

| Camada         | Responsabilidade              |
| -------------- | ----------------------------- |
| Domain         | Modelar o domínio             |
| Application    | Orquestrar casos de uso       |
| Adapters       | Traduzir representações       |
| Infrastructure | Fornecer capacidades externas |

Cada responsabilidade pertence exclusivamente à sua camada.

---

# 7. Relationships

As camadas possuem relacionamentos explícitos.

```text
Application
        │
        ▼
Domain

Application
        │
        ▼
Output Ports

Adapters
        │
        ▼
Application

Infrastructure
        │
        ▼
Adapters
```

Relacionamentos adicionais devem ser definidos por Engineering Standards específicos.

---

# 8. Dependency Direction

Dependências seguem apenas uma direção.

Dependências nunca retornam para camadas superiores.

Nenhuma camada pode depender de detalhes pertencentes a uma camada inferior.

---

# 9. Architectural Boundaries

Cada camada representa um limite arquitetural.

Esses limites existem para:

- preservar independência;
- reduzir acoplamento;
- facilitar evolução;
- permitir substituição de tecnologias.

Nenhuma camada deve assumir responsabilidades pertencentes a outra.

---

# 10. Architectural Constraints

O Blueprint estabelece as seguintes restrições.

- Camadas possuem responsabilidades exclusivas.
- Dependências seguem direção única.
- Camadas inferiores nunca redefinem conceitos superiores.
- Camadas superiores desconhecem implementações concretas.
- Implementações pertencem às camadas inferiores.

---

# 11. Representation Independence

Este documento não define:

- estrutura de diretórios;
- namespaces;
- pacotes;
- módulos;
- frameworks;
- tecnologias;
- linguagens.

Esses aspectos pertencem aos Language Standards e Technology Standards.

---

# 12. Architectural Compliance

Uma arquitetura está em conformidade quando:

- respeita as responsabilidades das camadas;
- preserva os limites arquiteturais;
- mantém dependências unidirecionais;
- evita acoplamento entre responsabilidades;
- mantém independência entre conceitos e implementações.

---

# 13. Architectural Violations

Constituem violações arquiteturais:

- misturar responsabilidades entre camadas;
- permitir dependências em sentido contrário;
- introduzir conceitos de infraestrutura nas camadas superiores;
- permitir que detalhes tecnológicos alterem responsabilidades arquiteturais.

---

# 14. Architecture Review Checklist

Antes da aprovação de qualquer alteração arquitetural verificar:

- [ ] As responsabilidades permanecem claras?
- [ ] Existe apenas uma direção de dependência?
- [ ] Houve mistura de responsabilidades?
- [ ] Alguma camada passou a conhecer detalhes de implementação?
- [ ] Os limites arquiteturais continuam preservados?

---

# 15. AI Interpretation

Ao interpretar este documento um agente deve concluir que:

- Camadas organizam responsabilidades.
- Camadas não representam tecnologias.
- Dependências possuem direção única.
- Implementações não alteram conceitos.
- A arquitetura permanece independente da linguagem utilizada.

---

# 16. References

Este documento complementa:

- ES-000 — Engineering Principles

É complementado por:

- ES-002 — Architectural Dependencies
- ES-003 — Domain Model
- ES-004 — Application Model
- ES-009 — Adapter Model
- ES-011 — Infrastructure Model

Os relacionamentos completos entre as camadas são definidos pelos documentos META do Blueprint.


## Section: Hinge — Where Does This Concept Live?

Placement classifica um novo conceito por responsabilidade.
  capability is pure business knowledge (invariant, behavior)
    -> Domain (ES-003)
  capability orchestrates Domain logic to fulfill a use case
    -> Application / Use Case (ES-008)
  capability translates an external representation (HTTP, persistence, third-party)
    -> Adapter (ES-009)
  capability is the boundary contract consumed by Use Cases
    -> Input Port (ES-006) or Output Port (ES-007)

Full rule: see Layer Responsibilities section.
