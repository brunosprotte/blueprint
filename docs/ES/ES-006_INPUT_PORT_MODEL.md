---
type: EngineeringStandard
title: "ES-006 — Input Port Model"
description: "Qual é o papel de um Input Port no modelo arquitetural do Blueprint?"
tags: [ES-006_INPUT_PORT_MODEL]
timestamp: "2026-07-04T18:12:56Z"
---

# ES-006 — Input Port Model

> **Engineering Standard**

| Campo           | Valor                 |
| --------------- | --------------------- |
| **ID**          | ES-006                |
| **Título**      | Input Port Model      |
| **Versão**      | 2.0.0                 |
| **Status**      | Approved              |
| **Owner**       | Software Architecture |
| **Obrigatório** | Sim                   |
| **Aplica-se**   | Toda a Arquitetura    |

---

# 1. Architectural Question

Qual é o papel de um Input Port no modelo arquitetural do Blueprint?

---

# 2. Purpose

Este documento define o modelo arquitetural de Input Ports.

Um Input Port representa uma **abstração arquitetural** que expõe uma capacidade da Application.

Seu propósito é permitir que entidades externas solicitem capacidades sem conhecer sua implementação.

Input Ports definem fronteiras arquiteturais.

Nunca definem mecanismos de implementação.

---

# 3. Vocabulary

## Input Port

Abstração arquitetural responsável por expor uma capacidade da Application.

---

## Capability

Comportamento oferecido pela Application.

---

## Caller

Entidade que solicita a execução de uma capacidade.

---

## Input Boundary

Limite arquitetural através do qual capacidades podem ser solicitadas.

---

## Architectural Abstraction

Conceito utilizado para desacoplar responsabilidades arquiteturais de suas implementações.

---

# 4. Architectural Entity

### Entity

Input Port

---

### Nature

Abstração arquitetural.

---

### Responsibility

Definir uma fronteira de entrada para capacidades da Application.

---

### Architectural Owner

Application.

---

### Known By

Adapters.

---

### Knows

Contracts.

---

### Represented By

Language Standards.

---

### Implemented Through

Technology Standards.

---

### Lifecycle

Defined

↓

Represented

↓

Implemented

↓

Invoked

---

# 5. Responsibilities

Um Input Port possui apenas as seguintes responsabilidades.

- definir uma fronteira arquitetural;
- expor capacidades;
- desacoplar Adapters da Application;
- preservar a independência entre consumidores e implementações.

Um Input Port não:

- executa capacidades;
- coordena fluxos;
- contém regras de negócio;
- conhece infraestrutura.

---

# 6. Relationships

Um Input Port participa dos seguintes relacionamentos.

É conhecido por:

- Adapters.

É materializado por:

- uma representação da linguagem.

É realizado por:

- uma implementação da Application.

Troca informações através de:

- Contracts.

Nunca depende de:

- Infrastructure;
- tecnologias;
- protocolos;
- mecanismos externos.

---

# 7. Architectural Nature

Input Ports são **abstrações arquiteturais**.

A arquitetura exige abstrações.

A arquitetura não exige um mecanismo específico para representá-las.

A representação concreta de um Input Port depende exclusivamente da linguagem utilizada.

---

# 8. Boundary Integrity

A integridade de um Input Port é preservada quando:

- a capacidade permanece explícita;
- a implementação permanece desacoplada;
- consumidores conhecem apenas a abstração;
- mecanismos externos permanecem isolados.

---

# 9. Architectural Constraints

Input Ports devem permanecer independentes de:

- linguagem;
- tecnologia;
- infraestrutura;
- protocolos;
- mecanismos de comunicação;
- mecanismos de execução.

A responsabilidade de um Input Port termina na definição da fronteira arquitetural.

---

# 10. Representation Independence

Este documento deliberadamente não define:

- interfaces;
- traits;
- protocols;
- classes abstratas;
- funções;
- métodos;
- handlers;
- controllers;
- decorators;
- annotations.

Esses mecanismos representam apenas formas possíveis de materializar uma abstração arquitetural.

Sua definição pertence aos Language Standards.

---

# 11. Architectural Compliance

Uma implementação está em conformidade quando:

- toda capacidade possui uma abstração de entrada explícita;
- consumidores dependem apenas da abstração;
- implementações permanecem substituíveis;
- mecanismos tecnológicos permanecem externos à arquitetura.

---

# 12. Architectural Violations

Constituem violações arquiteturais:

- permitir que consumidores dependam diretamente da implementação;
- utilizar Input Ports para implementar capacidades;
- permitir dependências tecnológicas na fronteira arquitetural;
- compartilhar responsabilidades entre abstração e implementação.

---

# 13. Architecture Review Checklist

Antes da aprovação de qualquer alteração verificar:

- [ ] O Input Port representa apenas uma abstração?
- [ ] A implementação permanece desacoplada?
- [ ] Existe alguma dependência tecnológica?
- [ ] A fronteira arquitetural permanece explícita?
- [ ] A abstração pode ser representada por diferentes linguagens sem alterar seu significado?

---

# 14. AI Interpretation

Ao interpretar este documento um agente deve concluir que:

- Um Input Port é uma abstração arquitetural.
- A arquitetura exige abstrações, não mecanismos específicos.
- Consumidores dependem da abstração.
- A representação pertence aos Language Standards.
- A implementação pertence aos Technology Standards.

---

# 15. References

Este documento complementa:

- ES-000 — Engineering Principles
- ES-001 — Architectural Layers
- ES-002 — Architectural Dependencies
- ES-004 — Application Model
- ES-005 — Contract Model

É complementado por:

- ES-007 — Output Port Model
- ES-008 — Use Case Model
- ES-009 — Adapter Model

As representações de Input Ports pertencem aos Language Standards.

As implementações pertencem aos Technology Standards.


## Section: Hinge — When to Create an Input Port

Input Port = boundary contract the Application exposes to the outside world.
  capability is invoked by an external actor (HTTP, CLI, queue, scheduler)?
    -> YES: define Input Port (interface)
    the actor's adapter implements the Input Port
  capability is internal flow between Application services?
    -> NO Input Port; call the use case directly
  capability is a Domain behavior triggered by an event handler?
    -> YES if the event is external; otherwise NO

Full rule: Input Port Definition + Implementation Pattern sections.
