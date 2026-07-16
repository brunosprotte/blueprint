---
type: EngineeringStandard
title: "ES-010 — Application Failure Model"
description: "Como a arquitetura representa situações em que uma operação não pode produzir o resultado esperado?"
tags: [ES-010_APPLICATION_FAILURE_MODEL]
timestamp: "2026-07-04T18:36:18Z"
---

# ES-010 — Application Failure Model

> **Engineering Standard**

| Campo           | Valor                     |
| --------------- | ------------------------- |
| **ID**          | ES-010                    |
| **Título**      | Application Failure Model |
| **Versão**      | 1.0.0                     |
| **Status**      | Approved                  |
| **Owner**       | Software Architecture     |
| **Obrigatório** | Sim                       |
| **Aplica-se**   | Toda a Arquitetura        |

---

# 1. Architectural Question

Como a arquitetura representa situações em que uma operação não pode produzir o resultado esperado?

---

# 2. Purpose

Este documento define o modelo arquitetural de Application Failures.

Uma Application Failure representa uma condição conhecida que impede a conclusão bem-sucedida de uma operação.

Application Failures preservam significado arquitetural sem depender de linguagem, protocolo, framework ou tecnologia.

---

# 3. Vocabulary

## Application Failure

Condição conhecida pela arquitetura que impede uma operação de produzir o resultado esperado.

---

## Failure Category

Classificação arquitetural de uma Application Failure.

---

## Failure Identifier

Identificador estável e único de uma Application Failure.

---

## Failure Propagation

Movimento de uma Application Failure entre entidades arquiteturais.

---

## Failure Translation

Conversão de uma Application Failure para uma representação externa.

---

## Failure Consumer

Entidade externa que interpreta a representação traduzida de uma Application Failure.

---

# 4. Architectural Entity

### Entity

Application Failure

---

### Nature

Conceito arquitetural.

---

### Responsibility

Representar falhas conhecidas preservando significado arquitetural.

---

### Architectural Owner

Application.

---

### Known By

- Domain
- Application
- Adapters

---

### Represented By

Language Standards.

---

### Implemented Through

Technology Standards.

---

### Lifecycle

Identified

↓

Categorized

↓

Propagated

↓

Translated

↓

Consumed

---

# 5. Failure Categories

O Blueprint define as seguintes categorias oficiais:

- Business Failure
- Validation Failure
- Authentication Failure
- Authorization Failure
- Infrastructure Failure
- Unexpected Failure

Cada Application Failure pertence exatamente a uma categoria.

Novas categorias exigem decisão arquitetural explícita.

---

# 6. Responsibilities

Uma Application Failure possui apenas as seguintes responsabilidades:

- representar uma condição de falha conhecida;
- preservar significado;
- informar categoria;
- informar identificador estável;
- carregar contexto quando necessário.

Uma Application Failure não:

- define protocolo;
- define transporte;
- define resposta externa;
- define mecanismo de linguagem;
- executa recuperação da falha.

---

# 7. Failure Ownership

Cada entidade arquitetural pode produzir apenas categorias compatíveis com sua responsabilidade.

| Entidade Arquitetural | Pode Produzir                                                   |
| --------------------- | --------------------------------------------------------------- |
| Domain                | Business Failure                                                |
| Application           | Business Failure, Authorization Failure                         |
| Input Adapter         | Validation Failure, Authentication Failure, Failure Translation |
| Output Adapter        | Infrastructure Failure                                          |
| Technology            | Infrastructure Failure                                          |
| Unknown Source        | Unexpected Failure                                              |

A categoria deve refletir a origem arquitetural da falha.

---

# 8. Relationships

Application Failures participam dos seguintes relacionamentos:

- podem ser produzidas pelo Domain;
- podem ser produzidas pela Application;
- podem ser produzidas por Adapters;
- propagam-se em direção ao limite de entrada;
- são traduzidas por Adapters;
- são consumidas por entidades externas após tradução.

Application Failures nunca dependem de:

- linguagem;
- tecnologia;
- protocolo;
- interface;
- infraestrutura específica.

---

# 9. Failure Contract

Toda Application Failure possui conceitualmente:

- Identifier
- Category
- Description
- Metadata
- Cause

A presença obrigatória ou opcional desses elementos é definida pelos Language Standards.

A forma de exposição desses elementos é definida pelos Technology Standards.

---

# 10. Failure Propagation

Application Failures propagam-se no sentido da arquitetura.

```text
Domain

↓

Application

↓

Input Adapter
```

Nenhuma entidade inferior conhece a representação externa da falha.

Nenhuma entidade superior deve depender de mecanismo de falha específico da linguagem.

---

# 11. Failure Translation

Failure Translation é responsabilidade de Adapters.

A tradução converte uma Application Failure para uma representação externa preservando seu significado.

A arquitetura não define:

- protocolo;
- status;
- payload;
- serialização;
- formato de mensagem;
- mecanismo de transporte.

---

# 12. Failure Semantics

Application Failures representam significado, não mecanismo.

A mesma Application Failure deve manter o mesmo significado independentemente de:

- linguagem;
- framework;
- protocolo;
- tecnologia;
- interface consumidora.

---

# 13. Representation Independence

Este documento deliberadamente não define:

- exceptions;
- errors;
- result types;
- status codes;
- payloads;
- classes;
- interfaces;
- traits;
- structs;
- handlers;
- catch blocks;
- retry mechanisms.

Esses aspectos pertencem aos Language Standards, Patterns e Technology Standards.

---

# 14. Architectural Compliance

Uma implementação está em conformidade quando:

- cada falha conhecida possui categoria clara;
- cada falha conhecida possui identificador estável;
- falhas preservam significado arquitetural;
- tradução ocorre apenas nos Adapters;
- o Core permanece independente de protocolo;
- a representação concreta pertence à linguagem.

---

# 15. Architectural Violations

Constituem violações arquiteturais:

- usar mecanismo de linguagem como conceito arquitetural;
- acoplar uma falha a protocolo específico;
- traduzir falhas fora dos Adapters;
- permitir que infraestrutura defina falhas de negócio;
- permitir que falhas externas alterem conceitos do Domain;
- representar falhas conhecidas como falhas inesperadas.

---

# 16. Decision Table

| Situação                         | Categoria              |
| -------------------------------- | ---------------------- |
| Regra de negócio não satisfeita  | Business Failure       |
| Entrada estruturalmente inválida | Validation Failure     |
| Identidade ausente ou inválida   | Authentication Failure |
| Permissão insuficiente           | Authorization Failure  |
| Capacidade externa indisponível  | Infrastructure Failure |
| Condição desconhecida            | Unexpected Failure     |

---

# 17. Architecture Review Checklist

Antes da aprovação de qualquer alteração verificar:

- [ ] A falha representa uma condição conhecida?
- [ ] A categoria está correta?
- [ ] Existe identificador estável?
- [ ] A falha preserva significado arquitetural?
- [ ] A falha permanece independente de linguagem?
- [ ] A falha permanece independente de protocolo?
- [ ] A tradução ocorre no limite arquitetural correto?

---

# 18. AI Interpretation

Ao interpretar este documento um agente deve concluir que:

- Application Failures são conceitos arquiteturais.
- Application Failures não são mecanismos de linguagem.
- Categorias indicam origem e significado.
- Identificadores devem ser estáveis.
- Translation pertence aos Adapters.
- Representação pertence aos Language Standards.
- Implementação pertence aos Technology Standards.

---

# 19. References

Este documento complementa:

- ES-003 — Domain Model
- ES-004 — Application Model
- ES-008 — Use Case Model
- ES-009 — Adapter Model

É complementado por:

- ES-011 — Architectural Boundary Model

As representações de Application Failures pertencem aos Language Standards.

As traduções para protocolos pertencem aos Technology Standards.
