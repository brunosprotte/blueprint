# ES-002 — Architectural Dependencies

> **Engineering Standard**

| Campo           | Valor                      |
| --------------- | -------------------------- |
| **ID**          | ES-002                     |
| **Título**      | Architectural Dependencies |
| **Versão**      | 1.0.0                      |
| **Status**      | Approved                   |
| **Owner**       | Software Architecture      |
| **Obrigatório** | Sim                        |
| **Aplica-se**   | Toda a Arquitetura         |

---

# 1. Architectural Question

Como entidades arquiteturais podem estabelecer relacionamentos sem comprometer a independência da arquitetura?

---

# 2. Purpose

Este documento define o modelo oficial de dependências arquiteturais do Blueprint.

Dependências representam relações de conhecimento entre entidades arquiteturais.

Seu objetivo é preservar:

- baixo acoplamento;
- independência entre conceitos;
- previsibilidade da arquitetura;
- evolução controlada.

Este documento define **quem pode conhecer quem**, mas não define como esse relacionamento é implementado.

---

# 3. Vocabulary

## Architectural Dependency

Relacionamento no qual uma entidade necessita conhecer outra para cumprir sua responsabilidade.

---

## Dependency Direction

Sentido permitido para uma dependência arquitetural.

---

## Dependency Boundary

Limite arquitetural atravessado por uma dependência.

---

## Architectural Coupling

Grau de conhecimento que uma entidade possui sobre outra.

---

## Dependency Graph

Conjunto de todas as dependências permitidas pela arquitetura.

---

# 4. Architectural Entity

### Entity

Architectural Dependency

---

### Responsibility

Definir os relacionamentos permitidos entre entidades arquiteturais.

---

### Architectural Owner

Software Architecture

---

### Known By

Todas as entidades arquiteturais.

---

### Represented By

Language Standards.

---

### Implemented Through

Technology Standards.

---

# 5. Principles

## AD-001 — Dependencies Represent Knowledge

Uma dependência representa conhecimento.

Não representa comunicação.

Não representa execução.

---

## AD-002 — Dependencies Are Explicit

Toda dependência arquitetural deve ser explícita.

Dependências implícitas não fazem parte do modelo arquitetural.

---

## AD-003 — Dependencies Are Directional

Toda dependência possui direção única.

Dependências cíclicas não pertencem ao modelo arquitetural.

---

## AD-004 — Dependencies Preserve Independence

Uma dependência nunca deve comprometer a independência conceitual da entidade dependente.

---

# 6. Dependency Relationships

O Blueprint define apenas relacionamentos explícitos.

Cada relacionamento representa uma necessidade arquitetural.

Exemplos de relacionamentos:

- depende de
- implementa
- representa
- traduz
- fornece
- consome

Novos relacionamentos devem ser introduzidos apenas quando representarem um novo conceito arquitetural.

---

# 7. Dependency Direction

Dependências seguem sempre o modelo arquitetural.

Uma entidade conhece apenas os conceitos necessários para cumprir sua responsabilidade.

Conhecimento desnecessário representa acoplamento arquitetural.

---

# 8. Dependency Boundaries

Toda dependência atravessa um limite arquitetural.

Esses limites existem para preservar:

- encapsulamento;
- independência;
- substituibilidade;
- evolução isolada.

Nenhuma dependência pode eliminar um limite arquitetural.

---

# 9. Dependency Rules

O Blueprint estabelece as seguintes regras.

- Dependências possuem direção única.
- Dependências representam necessidade arquitetural.
- Dependências nunca representam detalhes tecnológicos.
- Dependências preservam responsabilidades.
- Dependências não introduzem conhecimento desnecessário.

---

# 10. Architectural Constraints

Uma entidade arquitetural:

- conhece apenas os conceitos necessários;
- desconhece implementações concretas;
- desconhece tecnologias;
- desconhece representações específicas de linguagem.

---

# 11. Representation Independence

Este documento não define:

- mecanismos de injeção;
- importações;
- namespaces;
- módulos;
- pacotes;
- interfaces;
- classes;
- bibliotecas.

Esses mecanismos pertencem aos Language Standards.

---

# 12. Architectural Compliance

Uma arquitetura está em conformidade quando:

- todas as dependências possuem propósito arquitetural;
- não existem dependências cíclicas;
- responsabilidades permanecem isoladas;
- conceitos permanecem independentes;
- implementações não alteram a direção das dependências.

---

# 13. Architectural Violations

Constituem violações arquiteturais:

- dependências cíclicas;
- dependências implícitas;
- dependências motivadas por tecnologia;
- conhecimento desnecessário entre entidades;
- acoplamento entre conceitos independentes.

---

# 14. Architecture Review Checklist

Antes da aprovação de qualquer alteração arquitetural verificar:

- [ ] A dependência possui propósito arquitetural?
- [ ] A direção da dependência está correta?
- [ ] Existe conhecimento desnecessário?
- [ ] A dependência preserva a independência entre entidades?
- [ ] Alguma responsabilidade foi compartilhada indevidamente?
- [ ] Existe risco de dependência cíclica?

---

# 15. AI Interpretation

Ao interpretar este documento um agente deve concluir que:

- Dependências representam conhecimento arquitetural.
- Toda dependência possui direção.
- Dependências nunca representam tecnologia.
- A arquitetura deve minimizar acoplamento.
- Conhecimento desnecessário deve ser eliminado.

---

# 16. References

Este documento complementa:

- ES-000 — Engineering Principles
- ES-001 — Architectural Layers

É complementado por:

- ES-003 — Domain Model
- ES-004 — Application Model
- ES-005 — Contract Model
- ES-006 — Input Port Model
- ES-007 — Output Port Model
- ES-008 — Use Case Model
- ES-009 — Adapter Model

Os grafos completos de dependências arquiteturais são definidos pelos documentos META do Blueprint.
