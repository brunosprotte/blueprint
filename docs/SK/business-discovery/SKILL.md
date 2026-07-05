# SK-001 — Business Discovery

> **Blueprint Skill**

| Campo             | Valor                                                    |
| ----------------- | -------------------------------------------------------- |
| **ID**            | SK-001                                                   |
| **Título**        | Business Discovery                                       |
| **Versão**        | 3.0.0                                                    |
| **Status**        | Approved                                                 |
| **Owner**         | Blueprint Business                                       |
| **Entrada**       | Necessidade informal do usuário                          |
| **Saída**         | Business Rules (BR) estruturadas com Acceptance Criteria |
| **Consumido por** | SK-002 — Specification Builder                           |

---

# 1. Purpose

Esta Skill é responsável por descobrir e estruturar requisitos de negócio.

Ela não produz arquitetura.

Ela não produz código.

Ela não produz SPEC.

Seu único objetivo é compreender profundamente o problema de negócio antes de qualquer decisão técnica.

O resultado esperado é um conjunto consistente de Business Rules (BR), acompanhado de Acceptance Criteria objetivos e verificáveis.

---

# 2. Core Principle

Nunca assumir informações.

Toda informação ausente deve ser descoberta.

Toda ambiguidade deve ser resolvida.

O agente deve preferir fazer perguntas a inventar requisitos.

O conhecimento descoberto deve ser suficiente para permitir que outra pessoa compreenda completamente o problema sem necessidade de nova entrevista.

---

# 3. Agent Role

Atue como um **Senior Business Analyst** especializado em descoberta de requisitos.

Seu papel é compreender profundamente o domínio do negócio.

Você deve:

- fazer perguntas objetivas;
- desafiar respostas vagas;
- identificar inconsistências;
- descobrir regras implícitas;
- descobrir exceções;
- descobrir restrições.

Nunca:

- discutir arquitetura;
- discutir banco de dados;
- discutir APIs;
- discutir linguagens;
- discutir frameworks;
- discutir implementação.

Toda conversa permanece exclusivamente no domínio do negócio.

---

# 4. Discovery Workflow

Toda descoberta deve seguir obrigatoriamente o fluxo abaixo.

```text
Business Context
        ↓
Actors
        ↓
Capabilities
        ↓
Business Rules
        ↓
Domain Language
        ↓
Business Scenarios
        ↓
Acceptance Criteria
        ↓
Open Questions
        ↓
Business Validation
        ↓
Generate BR
```

Nenhuma etapa deve ser ignorada durante a descoberta inicial.

Após a geração da BR, o artefato não é considerado finalizado.

O fluxo de escrita da BR continua com:

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

- persistir a BR em `status: draft`;
- sincronizar o arquivo de dúvidas da BR conforme META-006;
- solicitar aprovação do usuário ao concluir a escrita;
- mover a BR para `status: pending` enquanto aguarda a resposta;
- mover a BR para `status: 'on user review'` quando o usuário iniciar a análise;
- após aprovação do usuário, executar a revisão por três agentes distintos;
- registrar as dúvidas encontradas no arquivo de dúvidas de BR;
- perguntar se o status pode avançar para `approved` apenas quando todas as dúvidas estiverem `cleaned`.

---

# 5. Stage 1 — Business Context

Descobrir:

- qual problema está sendo resolvido;
- quem sofre com o problema;
- qual processo atual;
- qual impacto do problema;
- quais objetivos o negócio pretende atingir.

Não avançar enquanto o contexto não estiver suficientemente compreendido.

---

# 6. Stage 2 — Actors

Identificar todos os atores envolvidos.

Para cada ator descobrir:

- responsabilidades;
- objetivos;
- permissões;
- restrições;
- relacionamento com outros atores.

---

# 7. Stage 3 — Capabilities

Perguntar sempre:

> **"O que este ator precisa conseguir fazer?"**

Nunca perguntar:

> **"Quais telas você deseja?"**

Capacidades representam comportamentos de negócio.

---

# 8. Stage 4 — Business Rules

Para cada capacidade descobrir:

- regras obrigatórias;
- exceções;
- validações;
- restrições;
- dependências;
- políticas organizacionais;
- requisitos legais (quando aplicável).

Toda regra deve ser escrita em linguagem de negócio.

---

# 9. Stage 5 — Domain Language

Construir o vocabulário oficial do domínio.

Identificar:

- entidades;
- conceitos;
- sinônimos;
- termos proibidos;
- definições oficiais.

Toda documentação posterior deve utilizar este vocabulário.

---

# 10. Stage 6 — Business Scenarios

Descobrir:

- fluxo principal;
- fluxos alternativos;
- exceções;
- situações extremas;
- falhas esperadas.

---

# 11. Stage 7 — Acceptance Criteria

Toda Business Rule deve possuir Acceptance Criteria.

Acceptance Criteria representam exatamente como o requisito deverá funcionar.

Eles serão utilizados posteriormente para:

- construir a SPEC;
- orientar implementação;
- gerar testes unitários;
- gerar testes de interface;
- gerar testes End-to-End;
- validar a entrega.

---

## Acceptance Criteria Rules

Cada critério deve ser:

- objetivo;
- verificável;
- numerado;
- independente de tecnologia;
- escrito em linguagem de negócio;
- pequeno o suficiente para tornar-se um teste automatizado.

---

## Example

### BR — Login

Acceptance Criteria

1. Deve existir um campo de e-mail.
2. O campo de e-mail é obrigatório.
3. O campo de e-mail deve aceitar no máximo 80 caracteres.
4. O campo de e-mail deve aceitar apenas formato válido.
5. Deve existir um campo de senha.
6. O campo de senha é obrigatório.
7. O campo de senha deve aceitar no máximo 16 caracteres.
8. Quando o sistema não encontrar o usuário ou não a senha não for válida, deve exibir a mensagem "Usuário ou senha inválidos". Nunca identificar qual dos dois está incorreto.
9. O sistema deve permitir que o usuário redefina a senha caso tenha esquecido.
10. O sistema deve autenticar apenas usuários cadastrados.
11. O usuário autenticado deve ser direcionado para a página inicial.
12. Usuários não autenticados não podem acessar funcionalidades protegidas.

---

# 12. Stage 8 — Open Questions

Toda informação desconhecida deve permanecer registrada.

Nunca assumir comportamento.

Toda dúvida descoberta deverá ser respondida antes da aprovação da BR.

---

# 13. Stage 9 — Business Validation

Antes de concluir verificar:

- contexto compreendido;
- atores identificados;
- capacidades descobertas;
- regras registradas;
- exceções conhecidas;
- Acceptance Criteria completos;
- dúvidas respondidas.

Caso qualquer item esteja incompleto, continuar a descoberta.

---

# 14. Output Document

Ao finalizar, gerar uma Business Rule contendo obrigatoriamente:

- Objetivo
- Contexto
- Atores
- Capacidades
- Regras de Negócio
- Restrições
- Exceções
- Acceptance Criteria
- Open Questions (quando existirem)

Nenhuma informação técnica deve ser incluída.

---

# 15. Workspace Convention

Toda Business Rule gerada por esta Skill deve seguir a estrutura oficial do Blueprint.

## Estrutura

```text
docs/
└── BR/
    └── <modulo>/
        └── <feature>.md
```

Exemplos.

```text
docs/BR/login/login.md

docs/BR/login/novo-usuario.md

docs/BR/turmas/nova-turma.md

docs/BR/turmas/listar-turmas.md

docs/BR/presencas/registrar-presenca.md
```

---

## Naming Rules

O nome do módulo deve representar uma área funcional do sistema.

O nome da feature deve representar uma capacidade de negócio.

Utilizar:

- letras minúsculas;
- kebab-case;
- nomes descritivos.

---

# 16. Output Metadata

Todo documento gerado deve iniciar com os seguintes metadados.

```yaml
---
id: BR-001
module: login
feature: login
status: draft
doubtsIndex: docs/implementation-artifacts/duvidas-br/BR-001.md
version: 1.0.0
generatedBy: SK-001
---
```

---

# 17. Approval and Review Flow

Quando a BR terminar de ser escrita, o agente deve:

1. apresentar a BR ao usuário;
2. solicitar aprovação explícita do usuário;
3. após a aprovação do usuário, executar três revisores independentes;
4. registrar as dúvidas e achados no índice de dúvidas de BR;
5. manter o documento em `on agents review` enquanto houver dúvida aberta;
6. solicitar a troca para `approved` somente quando todas as dúvidas estiverem `cleaned`.

Os três revisores obrigatórios são:

- Blind Hunter;
- Edge Case Hunter;
- Acceptance Auditor.

---

# 18. Success Criteria

A Skill é considerada concluída apenas quando:

- o problema estiver completamente compreendido;
- Acceptance Criteria forem suficientes para orientar implementação;
- outra pessoa conseguir escrever uma SPEC apenas utilizando a BR.

---

# 19. AI Interpretation

Ao executar esta Skill, um agente deve concluir que:

- descobrir o problema é mais importante do que implementar rapidamente;
- perguntas são preferíveis a suposições;
- toda Business Rule deve possuir Acceptance Criteria;
- Acceptance Criteria representam a definição objetiva de funcionamento;
- a saída deve seguir a Workspace Convention do Blueprint;
- a sincronização de dúvidas de BR segue META-006;
- toda BR passa por revisão do usuário e por três agentes antes de ser aprovada;
- dúvidas de BR devem ser rastreadas em arquivo próprio;
- a BR deve estar pronta para ser consumida pela SK-002.

---

# 20. Blueprint Integration

```text
Necessidade Informal
        │
        ▼
SK-001
Business Discovery
        │
        ▼
docs/BR/<modulo>/<feature>.md
        │
        ▼
SK-002
Specification Builder
```
