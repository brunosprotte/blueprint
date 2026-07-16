---
type: ReferenceImplementation
title: "RI-001 — Canonical CRUD Reference Implementation"
description: "Esta implementação de referência demonstra o fluxo completo de um CRUD seguindo o Blueprint."
tags: [RI-001_CANONICAL_CRUD_REFERENCE_IMPLEMENTATION]
timestamp: "2026-07-04T19:43:24Z"
---

# RI-001 — Canonical CRUD Reference Implementation

> **Reference Implementation**

| Campo        | Valor                                                                  |
| ------------ | ---------------------------------------------------------------------- |
| **ID**       | RI-001                                                                 |
| **Título**   | Canonical CRUD Reference Implementation                                |
| **Versão**   | 1.0.0                                                                  |
| **Status**   | Draft                                                                  |
| **Exemplo**  | Cadastro de Alunos                                                     |
| **Objetivo** | Demonstrar o fluxo completo Blueprint em TypeScript + Next.js + Prisma |

---

# 1. Purpose

Esta implementação de referência demonstra o fluxo completo de um CRUD seguindo o Blueprint.

O objetivo não é mostrar todas as telas possíveis.

O objetivo é fornecer um exemplo canônico que agentes possam reutilizar como base para novas funcionalidades.

---

# 2. Architecture Flow

```text
Page
↓
Service
↓
Route Handler
↓
Input Adapter Mapper
↓
Input Port
↓
Use Case
↓
Output Port
↓
Persistence Adapter
↓
Prisma
↓
Database
```

---

# 3. Feature

CRUD de Alunos.

Operações demonstradas:

- criar aluno;
- listar alunos;
- buscar aluno por ID;
- atualizar aluno;
- desativar aluno.

---

# 4. Folder Structure

```text
app/
├── (dashboard)/
│   └── alunos/
│       ├── page.tsx
│       └── components/
│           └── aluno-form.tsx
│
└── api/
    └── alunos/
        ├── route.ts
        └── [id]/
            └── route.ts

services/
├── api-client.ts
└── aluno.service.ts

core/
├── contracts/
│   └── aluno/
│       ├── create-aluno.request.ts
│       ├── create-aluno.response.ts
│       ├── list-alunos.response.ts
│       └── aluno-summary.response.ts
│
├── domain/
│   └── aluno.ts
│
├── ports/
│   ├── in/
│   │   ├── create-aluno.port.ts
│   │   └── list-alunos.port.ts
│   │
│   └── out/
│       └── aluno-repository.port.ts
│
└── useCases/
    └── aluno/
        ├── create-aluno.usecase.ts
        └── list-alunos.usecase.ts

adapters/
├── in/
│   ├── http/
│   │   └── api-response.ts
│   └── mappers/
│       └── aluno-http.mapper.ts
│
└── out/
    └── persistence/
        ├── prisma-aluno.repository.ts
        └── aluno-persistence.mapper.ts

infrastructure/
└── prisma/
    └── client.ts
```

---

# 5. Domain

```ts
export class Aluno {
  private constructor(
    readonly id: string,
    readonly nome: string,
    readonly cpf: string | null,
    readonly ativo: boolean,
  ) {}

  static criar(params: {
    readonly id: string;
    readonly nome: string;
    readonly cpf?: string;
  }): Aluno {
    return new Aluno(params.id, params.nome, params.cpf ?? null, true);
  }

  static restaurar(params: {
    readonly id: string;
    readonly nome: string;
    readonly cpf: string | null;
    readonly ativo: boolean;
  }): Aluno {
    return new Aluno(params.id, params.nome, params.cpf, params.ativo);
  }
}
```

---

# 6. Contracts

## create-aluno.request.ts

```ts
export type CreateAlunoRequest = {
  readonly nome: string;
  readonly cpf?: string;
};
```

## create-aluno.response.ts

```ts
export type CreateAlunoResponse = {
  readonly id: string;
  readonly nome: string;
};
```

## aluno-summary.response.ts

```ts
export type AlunoSummaryResponse = {
  readonly id: string;
  readonly nome: string;
  readonly ativo: boolean;
};
```

## list-alunos.response.ts

```ts
import type { AlunoSummaryResponse } from "./aluno-summary.response";

export type ListAlunosResponse = {
  readonly alunos: readonly AlunoSummaryResponse[];
};
```

---

# 7. Input Ports

## create-aluno.port.ts

```ts
export type CreateAlunoCommand = {
  readonly nome: string;
  readonly cpf?: string;
};

export type CreateAlunoResult = {
  readonly id: string;
  readonly nome: string;
};

export interface CreateAlunoInputPort {
  execute(command: CreateAlunoCommand): Promise<CreateAlunoResult>;
}
```

## list-alunos.port.ts

```ts
export type ListAlunosResult = {
  readonly alunos: readonly {
    readonly id: string;
    readonly nome: string;
    readonly ativo: boolean;
  }[];
};

export interface ListAlunosInputPort {
  execute(): Promise<ListAlunosResult>;
}
```

---

# 8. Output Port

```ts
import type { Aluno } from "@/core/domain/aluno";

export interface AlunoRepositoryPort {
  findByCpf(cpf: string): Promise<Aluno | null>;

  findAll(): Promise<readonly Aluno[]>;

  save(aluno: Aluno): Promise<Aluno>;
}
```

---

# 9. Use Cases

## create-aluno.usecase.ts

```ts
import { randomUUID } from "crypto";

import { Aluno } from "@/core/domain/aluno";

import type {
  CreateAlunoCommand,
  CreateAlunoInputPort,
  CreateAlunoResult,
} from "@/core/ports/in/create-aluno.port";

import type { AlunoRepositoryPort } from "@/core/ports/out/aluno-repository.port";

export class CreateAlunoUseCase implements CreateAlunoInputPort {
  constructor(private readonly alunoRepository: AlunoRepositoryPort) {}

  async execute(command: CreateAlunoCommand): Promise<CreateAlunoResult> {
    if (command.cpf) {
      const existente = await this.alunoRepository.findByCpf(command.cpf);

      if (existente) {
        throw new Error("ALUNO_DUPLICADO");
      }
    }

    const aluno = Aluno.criar({
      id: randomUUID(),
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

## list-alunos.usecase.ts

```ts
import type {
  ListAlunosInputPort,
  ListAlunosResult,
} from "@/core/ports/in/list-alunos.port";

import type { AlunoRepositoryPort } from "@/core/ports/out/aluno-repository.port";

export class ListAlunosUseCase implements ListAlunosInputPort {
  constructor(private readonly alunoRepository: AlunoRepositoryPort) {}

  async execute(): Promise<ListAlunosResult> {
    const alunos = await this.alunoRepository.findAll();

    return {
      alunos: alunos.map((aluno) => ({
        id: aluno.id,
        nome: aluno.nome,
        ativo: aluno.ativo,
      })),
    };
  }
}
```

---

# 10. Input Adapter Mapper

```ts
import type { CreateAlunoRequest } from "@/core/contracts/aluno/create-aluno.request";
import type { CreateAlunoResponse } from "@/core/contracts/aluno/create-aluno.response";
import type { ListAlunosResponse } from "@/core/contracts/aluno/list-alunos.response";
import type {
  CreateAlunoCommand,
  CreateAlunoResult,
} from "@/core/ports/in/create-aluno.port";
import type { ListAlunosResult } from "@/core/ports/in/list-alunos.port";

export class AlunoHttpMapper {
  static toCreateCommand(request: CreateAlunoRequest): CreateAlunoCommand {
    return {
      nome: request.nome,
      cpf: request.cpf,
    };
  }

  static toCreateResponse(result: CreateAlunoResult): CreateAlunoResponse {
    return {
      id: result.id,
      nome: result.nome,
    };
  }

  static toListResponse(result: ListAlunosResult): ListAlunosResponse {
    return {
      alunos: result.alunos,
    };
  }
}
```

---

# 11. Persistence Adapter

## aluno-persistence.mapper.ts

```ts
import { Aluno } from "@/core/domain/aluno";

export class AlunoPersistenceMapper {
  static toDomain(record: {
    readonly id: string;
    readonly nome: string;
    readonly cpf: string | null;
    readonly ativo: boolean;
  }): Aluno {
    return Aluno.restaurar({
      id: record.id,
      nome: record.nome,
      cpf: record.cpf,
      ativo: record.ativo,
    });
  }

  static toPersistence(aluno: Aluno) {
    return {
      id: aluno.id,
      nome: aluno.nome,
      cpf: aluno.cpf,
      ativo: aluno.ativo,
    };
  }
}
```

## prisma-aluno.repository.ts

```ts
import { prisma } from "@/infrastructure/prisma/client";
import { AlunoPersistenceMapper } from "@/adapters/out/persistence/aluno-persistence.mapper";

import type { Aluno } from "@/core/domain/aluno";
import type { AlunoRepositoryPort } from "@/core/ports/out/aluno-repository.port";

export class PrismaAlunoRepository implements AlunoRepositoryPort {
  async findByCpf(cpf: string): Promise<Aluno | null> {
    const record = await prisma.aluno.findUnique({
      where: { cpf },
    });

    if (!record) {
      return null;
    }

    return AlunoPersistenceMapper.toDomain(record);
  }

  async findAll(): Promise<readonly Aluno[]> {
    const records = await prisma.aluno.findMany({
      orderBy: {
        nome: "asc",
      },
    });

    return records.map(AlunoPersistenceMapper.toDomain);
  }

  async save(aluno: Aluno): Promise<Aluno> {
    const record = await prisma.aluno.create({
      data: AlunoPersistenceMapper.toPersistence(aluno),
    });

    return AlunoPersistenceMapper.toDomain(record);
  }
}
```

---

# 12. Infrastructure

## infrastructure/prisma/client.ts

```ts
import { PrismaClient } from "@prisma/client";

const globalForPrisma = globalThis as unknown as {
  prisma?: PrismaClient;
};

export const prisma = globalForPrisma.prisma ?? new PrismaClient();

if (process.env.NODE_ENV !== "production") {
  globalForPrisma.prisma = prisma;
}
```

---

# 13. Route Handler

## app/api/alunos/route.ts

```ts
import { NextRequest } from "next/server";

import { ApiResponse } from "@/adapters/in/http/api-response";
import { AlunoHttpMapper } from "@/adapters/in/mappers/aluno-http.mapper";
import { PrismaAlunoRepository } from "@/adapters/out/persistence/prisma-aluno.repository";
import { CreateAlunoUseCase } from "@/core/useCases/aluno/create-aluno.usecase";
import { ListAlunosUseCase } from "@/core/useCases/aluno/list-alunos.usecase";

import type { CreateAlunoInputPort } from "@/core/ports/in/create-aluno.port";
import type { ListAlunosInputPort } from "@/core/ports/in/list-alunos.port";

export async function GET(): Promise<Response> {
  const repository = new PrismaAlunoRepository();

  const inputPort: ListAlunosInputPort = new ListAlunosUseCase(repository);

  const result = await inputPort.execute();

  return ApiResponse.success(AlunoHttpMapper.toListResponse(result));
}

export async function POST(request: NextRequest): Promise<Response> {
  try {
    const body = await request.json();

    const command = AlunoHttpMapper.toCreateCommand(body);

    const repository = new PrismaAlunoRepository();

    const inputPort: CreateAlunoInputPort = new CreateAlunoUseCase(repository);

    const result = await inputPort.execute(command);

    return ApiResponse.success(AlunoHttpMapper.toCreateResponse(result), 201);
  } catch (failure) {
    return ApiResponse.failure(failure);
  }
}
```

---

# 14. API Response

```ts
export class ApiResponse {
  static success<T>(body: T, status = 200): Response {
    return Response.json(body, { status });
  }

  static failure(failure: unknown): Response {
    return Response.json(
      {
        code: "UNEXPECTED_FAILURE",
        message: "Não foi possível concluir a operação.",
      },
      {
        status: 500,
      },
    );
  }
}
```

---

# 15. Frontend Service

## services/api-client.ts

```ts
export class ApiClient {
  async get<ResponseBody>(url: string): Promise<ResponseBody> {
    const response = await fetch(url);

    if (!response.ok) {
      throw new Error("REQUEST_FAILURE");
    }

    return response.json() as Promise<ResponseBody>;
  }

  async post<RequestBody, ResponseBody>(
    url: string,
    body: RequestBody,
  ): Promise<ResponseBody> {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      throw new Error("REQUEST_FAILURE");
    }

    return response.json() as Promise<ResponseBody>;
  }
}

export const apiClient = new ApiClient();
```

## services/aluno.service.ts

```ts
import { apiClient } from "@/services/api-client";

import type { CreateAlunoRequest } from "@/core/contracts/aluno/create-aluno.request";
import type { CreateAlunoResponse } from "@/core/contracts/aluno/create-aluno.response";
import type { ListAlunosResponse } from "@/core/contracts/aluno/list-alunos.response";

class AlunoService {
  listar(): Promise<ListAlunosResponse> {
    return apiClient.get<ListAlunosResponse>("/api/alunos");
  }

  criar(request: CreateAlunoRequest): Promise<CreateAlunoResponse> {
    return apiClient.post<CreateAlunoRequest, CreateAlunoResponse>(
      "/api/alunos",
      request,
    );
  }
}

export const alunoService = new AlunoService();
```

---

# 16. Page

```tsx
import { AlunoForm } from "./components/aluno-form";

export default function AlunosPage() {
  return (
    <main>
      <h1>Alunos</h1>

      <AlunoForm />
    </main>
  );
}
```

---

# 17. Form Component

```tsx
"use client";

import { useState } from "react";

import { alunoService } from "@/services/aluno.service";

export function AlunoForm() {
  const [nome, setNome] = useState("");
  const [cpf, setCpf] = useState("");

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    await alunoService.criar({
      nome,
      cpf: cpf || undefined,
    });

    setNome("");
    setCpf("");
  }

  return (
    <form onSubmit={handleSubmit}>
      <label>
        Nome
        <input value={nome} onChange={(event) => setNome(event.target.value)} />
      </label>

      <label>
        CPF
        <input value={cpf} onChange={(event) => setCpf(event.target.value)} />
      </label>

      <button type="submit">Salvar</button>
    </form>
  );
}
```

---

# 18. Prisma Model

```prisma
model Aluno {
  id    String  @id
  nome  String
  cpf   String? @unique
  ativo Boolean @default(true)
}
```

---

# 19. Architectural Checklist

- [ ] Page não conhece Use Case.
- [ ] Service trafega apenas Contracts.
- [ ] Route Handler atua como Input Adapter.
- [ ] Mapper traduz Contract para Command.
- [ ] Input Port expõe capacidade.
- [ ] Use Case executa capacidade.
- [ ] Use Case depende de Output Port.
- [ ] Persistence Adapter implementa Output Port.
- [ ] Prisma não aparece no Core.
- [ ] Domain não conhece Contract.
- [ ] Adapter traduz representações.

---

# 20. Notes

Esta RI é propositalmente simples.

Ela não inclui ainda:

- autenticação;
- autorização;
- paginação;
- shadcn/ui;
- React Hook Form;
- Zod;
- tratamento avançado de failures;
- testes.

Esses itens serão adicionados em RIs específicas ou Technology Standards complementares.

O objetivo da RI-001 é demonstrar o fluxo completo mínimo do Blueprint.
