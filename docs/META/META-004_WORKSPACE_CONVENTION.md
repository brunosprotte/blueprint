# META-004 — Workspace Convention

> **Meta Document**

| Campo           | Valor                    |
| --------------- | ------------------------ |
| **ID**          | META-004                 |
| **Título**      | Workspace Convention     |
| **Versão**      | 1.0.0                    |
| **Status**      | Approved                 |
| **Owner**       | Blueprint Architecture   |
| **Obrigatório** | Sim                      |
| **Aplica-se**   | Todo Workspace Blueprint |

---

# 1. Purpose

Este documento define a organização oficial do Workspace Blueprint.

Seu objetivo é garantir que todo conhecimento produzido por agentes seja armazenado de forma previsível, rastreável e reutilizável.

A localização dos documentos faz parte da arquitetura do Blueprint.

Nenhuma Skill deve definir sua própria estrutura de diretórios.

---

# 2. Core Principle

O Workspace representa o repositório oficial de conhecimento do projeto.

Todo artefato gerado deve possuir:

- localização previsível;
- nomenclatura padronizada;
- rastreabilidade;
- organização consistente.

---

# 3. Workspace Structure

Todo projeto Blueprint deve utilizar a seguinte estrutura.

```text
docs/
│
├── BR/
│
├── PRD/
│
├── SPEC/
│
├── ADR/
│
├── ES/
│
├── PAT/
│
├── LS/
│
├── TS/
│
├── TP/
│
├── RI/
│
├── META/
│
└── SK/
```

Cada diretório representa uma categoria oficial do Blueprint.

Nenhuma categoria deve ser criada fora desta estrutura sem aprovação arquitetural.

---

# 4. Business Organization

Documentos de negócio devem ser organizados por módulo.

```text
docs/BR/

    login/

        login.md

        novo-usuario.md

    turmas/

        nova-turma.md

        listar-turmas.md

    presencas/

        registrar-presenca.md
```

A mesma organização aplica-se para:

```text
docs/PRD/

docs/SPEC/
```

---

# 5. Architecture Documents

Documentos arquiteturais permanecem na raiz da categoria.

```text
docs/ES/

    ES-000.md

    ES-001.md

    ...
```

O mesmo padrão aplica-se para.

```text
PAT

LS

TS

TP

RI

META

SK
```

---

# 6. Naming Convention

Módulos.

Utilizar.

```text
login

usuarios

turmas

presencas

notas
```

Sempre.

- minúsculas;
- sem espaços;
- kebab-case quando necessário.

---

Features.

Exemplos.

```text
novo-usuario

listar-usuarios

registrar-presenca

lancar-nota

consultar-presenca
```

---

# 7. File Convention

Todo documento deve possuir extensão.

```text
.md
```

Exemplo.

```text
docs/SPEC/login/login.md

docs/SPEC/login/novo-usuario.md
```

---

# 8. Document Metadata

Todo documento gerado automaticamente deve iniciar com metadados.

```yaml
---
id: SPEC-001
module: login
feature: login
status: draft
version: 1.0.0
generatedBy: SK-002
generatedAt: YYYY-MM-DD
---
```

Os metadados fazem parte do documento.

---

# 9. Artifact Ownership

Cada categoria é responsável por seus próprios documentos.

| Categoria | Responsável               |
| --------- | ------------------------- |
| BR        | SK-001                    |
| PRD       | SK-002 (quando aplicável) |
| SPEC      | SK-002                    |
| ADR       | Arquiteto                 |
| ES        | Arquitetura Blueprint     |
| PAT       | Arquitetura Blueprint     |
| LS        | Arquitetura Blueprint     |
| TS        | Arquitetura Blueprint     |
| TP        | Arquitetura Blueprint     |
| RI        | Arquitetura Blueprint     |
| META      | Arquitetura Blueprint     |
| SK        | Arquitetura Blueprint     |

Nenhuma Skill deve modificar documentos pertencentes a outra categoria sem autorização explícita.

---

# 10. Knowledge Traceability

Toda implementação deve possuir origem rastreável.

```text
Software

↑

RI

↑

TP

↑

TS

↑

LS

↑

PAT

↑

ES

↑

SPEC

↑

PRD

↑

BR
```

A localização física dos documentos deve facilitar essa rastreabilidade.

---

# 11. Workspace Evolution

Novos documentos devem respeitar a convenção existente.

Criar novas pastas somente quando:

- uma nova categoria oficial for aprovada;
- um ADR justificar a alteração.

Evitar estruturas paralelas.

---

# 12. AI Responsibilities

Ao gerar documentos o agente deve:

- identificar a categoria correta;
- identificar o módulo;
- identificar a feature;
- gerar o nome do arquivo;
- salvar na localização oficial;
- preencher os metadados.

O agente nunca deve perguntar onde salvar um documento.

---

# 13. Pending and Deferred Tracking

Toda dúvida, pendência ou decisão adiada deve ser registrada em um documento rastreador dentro de `docs/implementation-artifacts/`.

O Blueprint mantém rastreio separado por tipo de artefato.

## BR Doubts Index

- `docs/implementation-artifacts/duvidas-br/<BR-id>.md`

## SPEC Doubts Index

- `docs/implementation-artifacts/duvidas-spec/<SPEC-id>.md`

## Pending Catalogs

- `docs/implementation-artifacts/duvidas-br.md`
- `docs/implementation-artifacts/duvidas-spec.md`

Cada BR ou SPEC deve referenciar o respectivo arquivo de dúvidas no metadata do documento.

Os rastreadores oficiais devem usar somente estes status:

- `pending` para questões abertas;
- `deferred` para questões adiadas;
- `cleaned` para questões resolvidas.

Nenhuma BR, SPEC ou artefato de implementação deve manter dúvida relevante sem rastreabilidade em seu arquivo próprio.

Quando um item for resolvido, o status deve ser atualizado para `cleaned`.

Quando um item for postergado de forma consciente, o status deve ser atualizado para `deferred`.

Quando BRs e SPECs entrarem no ciclo de revisão, o status do artefato deve evoluir nesta sequência:

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

`pending` indica que o artefato foi gerado e aguarda revisão do usuário.

`on user review` indica que o usuário está revisando o artefato.

`on agents review` indica que os três revisores obrigatórios estão analisando o artefato.

`approved` só pode ser aplicado depois que todas as dúvidas relacionadas ao artefato estiverem `cleaned` e o usuário confirmar a promoção.

---

# 14. AI Interpretation

Ao interpretar este documento, um agente deve concluir que:

- o Workspace possui organização oficial;
- cada categoria possui uma localização única;
- documentos de negócio são organizados por módulo;
- documentos arquiteturais permanecem na raiz da categoria;
- toda saída deve respeitar esta convenção;
- a estrutura do Workspace faz parte da arquitetura do Blueprint.

---

# 15. References

Complementa:

- META-000 — Blueprint Knowledge Model
- META-001 — Knowledge Resolution Engine
- META-002 — Knowledge Evolution Model
- META-003 — Runtime Execution Model
- META-006 — Doubts Index Synchronization Flow

É utilizado por todas as Skills e agentes Blueprint.
