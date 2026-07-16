---
type: Meta
title: "META-003 — Runtime Execution Model"
description: "Este documento define como um agente Blueprint deve se comportar durante a execução."
tags: [META-003_RUNTIME_EXECUTION_MODEL]
timestamp: "2026-07-04T11:34:11Z"
---

# META-003 — Runtime Execution Model

> **Meta Document**

| Campo           | Valor                      |
| --------------- | -------------------------- |
| **ID**          | META-003                   |
| **Título**      | Runtime Execution Model    |
| **Versão**      | 1.0.0                      |
| **Status**      | Approved                   |
| **Owner**       | Blueprint Architecture     |
| **Obrigatório** | Sim                        |
| **Aplica-se**   | Todos os Agentes Blueprint |

---

# 1. Purpose

Este documento define como um agente Blueprint deve se comportar durante a execução.

Seu objetivo é impedir que diferentes etapas do processo de engenharia sejam misturadas.

O Runtime controla o comportamento do agente.

Não controla o conhecimento.

O conhecimento pertence aos documentos Blueprint.

---

# 2. Core Principle

Um agente executa apenas uma responsabilidade por vez.

Cada etapa possui um objetivo específico.

O agente nunca deve executar comportamentos pertencentes a outro estado.

---

# 3. Runtime State Machine

Toda execução deve seguir a seguinte máquina de estados.

```text
IDLE

↓

DISCOVERING

↓

MODELING

↓

SPECIFYING

↓

RESOLVING

↓

IMPLEMENTING

↓

VALIDATING

↓

DONE
```

O agente pode permanecer em um estado enquanto sua responsabilidade não estiver concluída.

---

# 4. State Responsibilities

## IDLE

Estado inicial.

Aguardando uma solicitação.

Pode:

- receber contexto;
- iniciar execução.

Não pode:

- produzir documentos;
- gerar código.

---

## DISCOVERING

Objetivo.

Descobrir conhecimento.

Pode:

- fazer perguntas;
- esclarecer ambiguidades;
- identificar atores;
- descobrir regras;
- descobrir restrições.

Não pode:

- gerar SPEC;
- gerar código;
- assumir comportamento.

---

## MODELING

Objetivo.

Organizar conhecimento.

Pode:

- estruturar BR;
- estruturar PRD;
- organizar domínio.

Não pode:

- implementar;
- escolher tecnologias.

---

## SPECIFYING

Objetivo.

Transformar conhecimento em especificações implementáveis.

Pode:

- criar SPEC;
- definir contratos;
- definir validações;
- definir fluxos.

Não pode:

- inventar requisitos;
- alterar BR.

---

## RESOLVING

Objetivo.

Resolver conhecimento.

Pode:

- localizar documentos;
- carregar ES;
- carregar PAT;
- carregar LS;
- carregar TS;
- carregar TP;
- carregar RI.

Utiliza META-001.

---

## IMPLEMENTING

Objetivo.

Materializar conhecimento.

Pode:

- gerar código;
- aplicar Technology Packs;
- utilizar Reference Implementations.

Não pode:

- alterar BR;
- alterar SPEC;
- inventar requisitos.

---

## VALIDATING

Objetivo.

Validar conformidade.

Pode:

- verificar arquitetura;
- verificar SPEC;
- verificar testes;
- verificar Acceptance Criteria.

Não pode:

- implementar novas funcionalidades;
- alterar requisitos.

---

## DONE

Execução concluída.

O agente aguarda uma nova solicitação.

---

# 5. Transition Rules

Cada estado possui transições válidas.

```text
IDLE

↓

DISCOVERING

↓

MODELING

↓

SPECIFYING

↓

RESOLVING

↓

IMPLEMENTING

↓

VALIDATING

↓

DONE
```

Retornos são permitidos apenas quando novas informações forem descobertas.

Exemplo.

```text
SPECIFYING

↓

DISCOVERING
```

Caso um requisito esteja incompleto.

---

# 6. Runtime Guard Rails

DISCOVERING

Nunca gera código.

---

MODELING

Nunca escolhe tecnologias.

---

SPECIFYING

Nunca cria regras de negócio.

---

RESOLVING

Nunca altera documentos.

---

IMPLEMENTING

Nunca altera BR.

Nunca altera SPEC.

---

VALIDATING

Nunca cria funcionalidades.

Nunca modifica arquitetura.

---

# 7. Runtime Responsibilities

Durante toda execução o agente deve:

- respeitar o estado atual;
- respeitar META-001;
- respeitar META-002;
- respeitar META-004;
- preservar rastreabilidade;
- evitar mudanças desnecessárias.

---

# 8. Runtime Resolution

Sempre que uma tarefa iniciar.

O agente deve responder.

1. Em qual estado estou?

2. Qual documento Blueprint governa este estado?

3. Qual deve ser a próxima transição?

Caso alguma resposta seja desconhecida.

A execução deve ser interrompida.

---

# 9. Runtime Failure

Caso uma execução não possa prosseguir.

O agente deve:

- informar claramente o motivo;
- identificar o conhecimento ausente;
- indicar qual documento precisa ser criado ou atualizado;
- permanecer no estado atual.

Nunca inventar informações para continuar.

---

# 10. AI Interpretation

Ao interpretar este documento um agente deve concluir que:

- execução é controlada por estados;
- cada estado possui responsabilidades próprias;
- conhecimento pertence aos documentos Blueprint;
- implementação nunca modifica requisitos;
- descoberta nunca produz código;
- validação nunca altera arquitetura;
- estados diferentes nunca devem ser misturados.

---

# 11. References

Este documento utiliza:

- META-000 — Blueprint Knowledge Model
- META-001 — Knowledge Resolution Engine
- META-002 — Knowledge Evolution Model
- META-004 — Workspace Convention

É utilizado por todas as Skills e agentes Blueprint.
