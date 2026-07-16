---
type: LanguageStandard
title: "LS-001 — TypeScript Representation Standard"
description: "Como representar os conceitos arquiteturais do Blueprint em TypeScript?"
tags: [LS-001_TYPESCRIPT_REPRESENTATION_STANDARD]
timestamp: "2026-07-04T19:32:10Z"
---

# LS-001 — TypeScript Representation Standard

> **Language Standard**

| Campo           | Valor                                          |
| --------------- | ---------------------------------------------- |
| **ID**          | LS-001                                         |
| **Título**      | TypeScript Representation Standard             |
| **Versão**      | 1.0.0                                          |
| **Status**      | Approved                                       |
| **Owner**       | Software Architecture                          |
| **Obrigatório** | Sim                                            |
| **Linguagem**   | TypeScript                                     |
| **Aplica-se**   | Projetos Blueprint implementados em TypeScript |
| **Depende de**  | ES-000 até ES-011                              |

---

# 1. Language Question

Como representar os conceitos arquiteturais do Blueprint em TypeScript?

---

# 2. Purpose

Este documento define como os conceitos dos Engineering Standards devem ser representados em TypeScript.

Os Engineering Standards definem conceitos.

Este documento define representações.

Este documento não define framework, biblioteca, ORM, protocolo ou tecnologia específica.

---

# 3. Representation Rules

## 3.1 Domain

Domain deve ser representado por tipos, classes ou objetos que preservem significado de negócio.

Exemplo recomendado para domínio com comportamento:

```ts
export class Aluno {
  private constructor(
    readonly id: string,
    readonly nome: string,
    readonly cpf: string | null,
  ) {}

  static criar(params: {
    readonly id: string;
    readonly nome: string;
    readonly cpf?: string;
  }): Aluno {
    return new Aluno(params.id, params.nome, params.cpf ?? null);
  }
}
```

---

## 3.2 Contract

Contract deve ser representado por `type` ou `interface`.

Contracts não devem conter comportamento.

```ts
export type CreateAlunoRequest = {
  readonly nome: string;
  readonly cpf?: string;
};

export type CreateAlunoResponse = {
  readonly id: string;
  readonly nome: string;
};
```

---

## 3.3 Input Port

Input Port deve ser representado por `interface`.

```ts
export interface CreateAlunoInputPort {
  execute(command: CreateAlunoCommand): Promise<CreateAlunoResult>;
}
```

---

## 3.4 Command

Command representa a entrada da Application.

```ts
export type CreateAlunoCommand = {
  readonly nome: string;
  readonly cpf?: string;
};
```

---

## 3.5 Result

Result representa a saída da Application.

```ts
export type CreateAlunoResult = {
  readonly id: string;
  readonly nome: string;
};
```

---

## 3.6 Output Port

Output Port deve ser representado por `interface`.

```ts
export interface AlunoRepositoryPort {
  findByCpf(cpf: string): Promise<Aluno | null>;

  save(aluno: Aluno): Promise<Aluno>;
}
```

---

## 3.7 Use Case

Use Case deve ser representado por `class`.

A classe deve implementar exatamente um Input Port.

```ts
export class CreateAlunoUseCase implements CreateAlunoInputPort {
  constructor(private readonly alunoRepository: AlunoRepositoryPort) {}

  async execute(command: CreateAlunoCommand): Promise<CreateAlunoResult> {
    const existente = command.cpf
      ? await this.alunoRepository.findByCpf(command.cpf)
      : null;

    if (existente) {
      throw new AlunoDuplicadoFailure(command.cpf);
    }

    const aluno = Aluno.criar({
      id: crypto.randomUUID(),
      nome: command.nome,
      cpf: command.cpf,
    });

    const salvo = await this.alunoRepository.save(aluno);

    return {
      id: salvo.id,
      nome: salvo.nome,
    };
  }
}
```

---

## 3.8 Adapter

Adapter deve ser representado por `class`.

Adapters podem implementar Output Ports ou consumir Input Ports.

```ts
export class AlunoPersistenceAdapter implements AlunoRepositoryPort {
  async findByCpf(cpf: string): Promise<Aluno | null> {
    // implementação concreta
    return null;
  }

  async save(aluno: Aluno): Promise<Aluno> {
    // implementação concreta
    return aluno;
  }
}
```

---

## 3.9 Mapper

Mapper deve ser representado por `class` com métodos estáticos ou funções puras.

```ts
export class CreateAlunoMapper {
  static toCommand(request: CreateAlunoRequest): CreateAlunoCommand {
    return {
      nome: request.nome,
      cpf: request.cpf,
    };
  }

  static toResponse(result: CreateAlunoResult): CreateAlunoResponse {
    return {
      id: result.id,
      nome: result.nome,
    };
  }
}
```

---

## 3.10 Application Failure

Application Failure deve ser representada por uma hierarquia baseada em `Error`.

```ts
export abstract class ApplicationFailure extends Error {
  protected constructor(
    readonly identifier: string,
    readonly category: FailureCategory,
    message: string,
    readonly metadata?: unknown,
    readonly cause?: unknown,
  ) {
    super(message);
    this.name = identifier;
  }
}
```

```ts
export type FailureCategory =
  | "BUSINESS"
  | "VALIDATION"
  | "AUTHENTICATION"
  | "AUTHORIZATION"
  | "INFRASTRUCTURE"
  | "UNEXPECTED";
```

```ts
export class AlunoDuplicadoFailure extends ApplicationFailure {
  constructor(cpf: string) {
    super(
      "ALUNO_DUPLICADO",
      "BUSINESS",
      "Já existe aluno cadastrado com este CPF.",
      { cpf },
    );
  }
}
```

---

# 4. File Naming

Arquivos TypeScript devem usar kebab-case.

```text
create-aluno.usecase.ts
create-aluno.port.ts
aluno-repository.port.ts
create-aluno.mapper.ts
aluno.ts
```

---

# 5. Import Rules

Imports devem seguir esta ordem:

1. Bibliotecas externas
2. Imports internos absolutos
3. Imports relativos
4. Type imports

Sempre usar `import type` quando o símbolo for usado apenas como tipo.

---

# 6. TypeScript Constraints

O projeto deve usar TypeScript estrito.

Obrigatório:

```text
strict
noImplicitAny
strictNullChecks
noUncheckedIndexedAccess
exactOptionalPropertyTypes
```

Proibido:

```text
any
as any
@ts-ignore
@ts-nocheck
```

---

# 7. Canonical Flow

```text
Contract
↓
Mapper
↓
Command
↓
Input Port
↓
Use Case
↓
Output Port
↓
Adapter
↓
Result
↓
Mapper
↓
Contract
```

---

# 8. Compliance Checklist

- [ ] Domain preserva significado de negócio.
- [ ] Contracts não possuem comportamento.
- [ ] Input Port é `interface`.
- [ ] Output Port é `interface`.
- [ ] Use Case é `class`.
- [ ] Use Case implementa um Input Port.
- [ ] Adapter implementa Output Port quando fornece capacidade externa.
- [ ] Mapper traduz representações.
- [ ] Failures estendem `ApplicationFailure`.
- [ ] `import type` usado corretamente.
- [ ] Nenhum `any` foi introduzido.

---

# 9. AI Interpretation

Ao implementar Blueprint em TypeScript, o agente deve:

- representar Ports como interfaces;
- representar Use Cases como classes;
- representar Contracts como tipos sem comportamento;
- representar Failures com `ApplicationFailure`;
- manter framework e tecnologia fora deste documento;
- consultar Technology Standards para implementação concreta.

---

# 10. References

Este documento é consumido por Technology Standards compatíveis com TypeScript.
