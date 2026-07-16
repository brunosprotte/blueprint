# ARQUITETURA_HEXAGONAL_NEXTJS.md

# Arquitetura Oficial do Projeto

## Objetivo

Este documento define a arquitetura oficial do sistema de gestão de cursos de português para imigrantes.

Toda implementação deve seguir obrigatoriamente as regras descritas neste documento.

Os objetivos da arquitetura são:

- Separação de responsabilidades
- Baixo acoplamento
- Alta testabilidade
- Independência do framework
- Facilidade de manutenção
- Facilidade para evolução
- Compatibilidade com Spec Driven Development
- Compatibilidade com IA (Claude, ChatGPT, Copilot)

---

# Princípios

O domínio da aplicação nunca deve depender do framework.

Isso significa que as regras de negócio não conhecem:

- Next.js
- React
- Prisma
- PostgreSQL
- Supabase
- Fetch API
- HTTP
- Cookies
- LocalStorage

O domínio conhece apenas:

- Entidades
- Casos de uso
- Regras de negócio
- Interfaces (Ports)

---

# Arquitetura

A aplicação segue o modelo Hexagonal (Ports & Adapters).

Fluxo completo:

```
Browser
    │
    ▼
Page (React)
    │
    ▼
Frontend Service
    │
    ▼
Route Handler (Adapter In)
    │
    ▼
Use Case
    │
    ▼
Port
    │
    ▼
Repository (Adapter Out)
    │
    ▼
Prisma
    │
    ▼
PostgreSQL
```

As dependências sempre apontam para dentro.

Nunca no sentido contrário.

---

# Estrutura Oficial

```
app/
│
├── (auth)
│     ├── login
│     └── recuperar-senha
│
├── (dashboard)
│     ├── alunos
│     ├── turmas
│     ├── aulas
│     ├── presencas
│     ├── avaliacoes
│     └── configuracoes
│
├── api
│     ├── auth
│     ├── alunos
│     ├── turmas
│     ├── aulas
│     ├── presencas
│     └── avaliacoes
│
├── layout.tsx
└── page.tsx

components/

services/

core/
│
├── domain/
├── ports/
├── useCases/
└── dto/

adapters/
│
├── in/
└── out/

infrastructure/
│
├── prisma/
├── auth/
├── config/
└── logger/

tests/
```

---

# Responsabilidade de Cada Camada

## app/

Responsável pela interface da aplicação.

Contém:

- páginas
- layouts
- navegação
- Route Handlers

Nunca contém:

- regras de negócio
- consultas Prisma
- acesso ao banco

---

# components/

Contém componentes reutilizáveis.

Exemplos:

- Button
- Table
- Form
- Input
- Modal
- Sidebar

Componentes nunca fazem chamadas HTTP.

Recebem dados por propriedades.

---

# services/

Responsável pela comunicação entre Frontend e Backend.

Toda chamada HTTP deve passar por esta camada.

Exemplo:

```
AlunoService

↓

GET /api/alunos
```

Nunca utilizar:

```
fetch(...)
```

Dentro de:

- page.tsx

- components

---

# app/api

Representa a entrada da aplicação.

É o Adapter In da Arquitetura Hexagonal.

Cada rota deve apenas:

- receber requisição
- validar entrada
- chamar um Use Case
- retornar resposta

Nunca conter:

- regras de negócio
- consultas Prisma

---

# core/domain

Contém:

- entidades
- enums
- value objects
- regras do domínio

Não conhece:

- banco
- React
- Next.js

---

# core/useCases

É o coração da aplicação.

Toda regra de negócio deve existir nesta camada.

Exemplos:

- CriarAlunoUseCase
- CriarTurmaUseCase
- RegistrarPresencaUseCase
- LancarNotaUseCase

Use Cases utilizam apenas Ports.

Nunca utilizam Prisma.

---

# core/ports

Define contratos.

Exemplo:

```ts
export interface AlunoRepository {
  salvar();

  buscarPorId();

  buscarPorCpf();
}
```

Nenhuma implementação existe nesta camada.

---

# core/dto

Contém DTOs utilizados pelos Use Cases.

Exemplo:

```
CreateAlunoDTO

UpdateAlunoDTO

CreateTurmaDTO

RegistrarPresencaDTO
```

---

# adapters/out

Implementa os Ports.

Exemplo:

```
AlunoPrismaRepository

TurmaPrismaRepository

PresencaPrismaRepository
```

Responsável por:

- Prisma
- SQL
- PostgreSQL

Nunca conter:

- regras de negócio

---

# adapters/in

Opcional.

Utilizado para:

- Mappers
- Validators
- Conversores
- Presenters

Exemplo:

```
AlunoMapper

AlunoValidator

CreateAlunoRequest
```

Não contém regras de negócio.

---

# infrastructure

Contém dependências externas.

Exemplos:

- PrismaClient
- configuração
- autenticação
- logger
- variáveis de ambiente

---

# Fluxo Oficial

Cadastro de aluno.

```
AlunoPage

↓

AlunoService.create()

↓

POST /api/alunos

↓

CreateAlunoRoute

↓

CreateAlunoUseCase

↓

AlunoRepository

↓

AlunoPrismaRepository

↓

Prisma

↓

PostgreSQL
```

---

# Regras Obrigatórias

## Pages

Podem:

- renderizar interface
- chamar Services

Não podem:

- fetch
- axios
- Prisma
- regras de negócio

---

## Components

Podem:

- renderizar interface

Não podem:

- acessar APIs
- acessar banco

---

## Services

Podem:

- fetch
- tratamento HTTP

Não podem:

- regras de negócio

---

## Route Handlers

Podem:

- validar Request
- validar autenticação
- chamar Use Cases

Não podem:

- Prisma direto
- regras de negócio

---

## Use Cases

Podem:

- executar regras
- chamar Ports

Não podem:

- conhecer React
- conhecer Next.js
- conhecer Prisma

---

## Repository

Pode:

- executar consultas
- utilizar Prisma

Não pode:

- conter regra de negócio

---

# Injeção de Dependência

Os Use Cases nunca instanciam Repositories.

Correto:

```ts
const repository = new AlunoPrismaRepository();

const useCase = new CreateAlunoUseCase(repository);
```

Nunca:

```ts
class CreateAlunoUseCase {
  constructor() {
    this.repository = new PrismaClient();
  }
}
```

---

# Organização por Funcionalidade

Cada funcionalidade deve possuir:

```
CreateAlunoDTO

↓

CreateAlunoUseCase

↓

AlunoRepository

↓

AlunoPrismaRepository

↓

Route

↓

AlunoService
```

---

# Testes

Os testes devem ser divididos em:

```
Unitários

Integração

E2E
```

Use Cases devem possuir testes unitários.

Repositories devem possuir testes de integração.

---

# Convenções

Classes:

```
CreateAlunoUseCase
```

Interfaces:

```
AlunoRepository
```

Repositories:

```
AlunoPrismaRepository
```

Services:

```
AlunoService
```

DTOs:

```
CreateAlunoDTO
```

Enums:

```
TipoUsuario
```

---

# Regra Mais Importante

Toda regra de negócio deve existir em apenas um lugar.

```
core/useCases
```

As demais camadas apenas transportam informações.

---

# Objetivo Final

A arquitetura deve garantir:

- código organizado
- domínio isolado
- fácil manutenção
- fácil escalabilidade
- alta cobertura de testes
- compatibilidade com IA
- independência do framework
- baixo acoplamento
- alta coesão
