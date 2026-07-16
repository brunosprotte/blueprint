---
type: TechnologyStandard
title: "TS-001 — Next.js Standard"
description: "Como materializar os conceitos do Blueprint usando Next.js?"
tags: [TS-001_NEXTJS_STANDARDS]
timestamp: "2026-07-04T18:53:24Z"
---

# TS-001 — Next.js Standard

> **Technology Standard**

| Campo          | Valor                                        |
| -------------- | -------------------------------------------- |
| **ID**         | TS-001                                       |
| **Título**     | Next.js Standard                             |
| **Versão**     | 1.0.0                                        |
| **Status**     | Approved                                     |
| **Tecnologia** | Next.js                                      |
| **Aplica-se**  | Projetos Blueprint usando Next.js App Router |
| **Depende de** | ES-000 até ES-011, LS-001                    |

---

# 1. Technology Question

Como materializar os conceitos do Blueprint usando Next.js?

---

# 2. Purpose

Este documento define como Next.js deve ser utilizado em projetos Blueprint.

Next.js é tecnologia de entrega.

Next.js não define arquitetura.

A arquitetura continua sendo definida pelos Engineering Standards.

---

# 3. Architecture Mapping

| Conceito Blueprint  | Representação em Next.js |
| ------------------- | ------------------------ |
| Input Adapter       | Route Handler            |
| UI Adapter          | Page / Component         |
| Contract            | Type compartilhado       |
| Input Port          | Interface TypeScript     |
| Use Case            | Classe TypeScript        |
| Output Port         | Interface TypeScript     |
| Output Adapter      | Implementação concreta   |
| Failure Translation | API Response Mapper      |

---

# 4. App Router

O projeto deve utilizar App Router.

Páginas ficam em:

```text
app/
```

APIs ficam em:

```text
app/api/
```

---

# 5. Pages

Pages são UI Adapters.

Responsabilidade:

- renderizar tela;
- compor componentes;
- consumir services;
- nunca conter regra de negócio.

Pages não acessam Use Cases diretamente.

---

# 6. Services

Services são clientes HTTP do Frontend.

Fluxo obrigatório:

```text
Page / Component
↓
Service
↓
Route Handler
```

Service trafega apenas Contracts.

---

# 7. Route Handlers

Route Handlers são Input Adapters.

Responsabilidade:

- receber request;
- validar entrada;
- traduzir Contract para Command;
- chamar Input Port;
- traduzir Result para Response Contract;
- traduzir Failures.

---

# 8. Forbidden

Route Handlers não podem conter regra de negócio.

Pages não podem chamar Use Cases.

Components não podem fazer persistência.

Services não podem importar Domain, Ports ou Use Cases.

---

# 9. Suggested Structure

```text
app/
├── (auth)/
│   └── login/
│       └── page.tsx
│
├── (dashboard)/
│   ├── alunos/
│   │   └── page.tsx
│   ├── turmas/
│   │   └── page.tsx
│   └── presencas/
│       └── page.tsx
│
└── api/
    ├── alunos/
    │   └── route.ts
    ├── turmas/
    │   └── route.ts
    └── presencas/
        └── route.ts

components/

services/

core/

adapters/

infrastructure/
```

---

# 10. Route Handler Example

```ts
import { NextRequest } from "next/server";

import { CreateAlunoMapper } from "@/adapters/in/mappers/create-aluno.mapper";
import { ApiResponse } from "@/adapters/in/http/api-response";
import { AlunoPersistenceAdapter } from "@/adapters/out/persistence/aluno-persistence.adapter";
import { CreateAlunoUseCase } from "@/core/useCases/aluno/create-aluno.usecase";

import type { CreateAlunoInputPort } from "@/core/ports/in/create-aluno.port";

export async function POST(request: NextRequest): Promise<Response> {
  try {
    const body = await request.json();

    const command = CreateAlunoMapper.toCommand(body);

    const alunoRepository = new AlunoPersistenceAdapter();

    const inputPort: CreateAlunoInputPort = new CreateAlunoUseCase(
      alunoRepository,
    );

    const result = await inputPort.execute(command);

    return ApiResponse.success(CreateAlunoMapper.toResponse(result), 201);
  } catch (failure) {
    return ApiResponse.failure(failure);
  }
}
```

---

# 11. Service Example

```ts
import { apiClient } from "@/services/api-client";

import type { CreateAlunoRequest } from "@/core/contracts/aluno/create-aluno.request";
import type { CreateAlunoResponse } from "@/core/contracts/aluno/create-aluno.response";

class AlunoService {
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

# 12. Page Example

```tsx
import { AlunoForm } from "./components/aluno-form";

export default function AlunosPage() {
  return (
    <main>
      <AlunoForm />
    </main>
  );
}
```

---

# 13. Client Components

Usar `"use client"` apenas quando houver necessidade de interatividade.

Exemplos:

- formulário;
- estado local;
- eventos de clique;
- modal;
- validação de input;
- integração com browser APIs.

---

# 14. Server Components

Server Components são o padrão.

Não adicionar `"use client"` sem necessidade.

---

# 15. API Response

Toda resposta HTTP deve passar por helper central.

```ts
export class ApiResponse {
  static success<T>(body: T, status = 200): Response {
    return Response.json(body, { status });
  }

  static failure(failure: unknown): Response {
    return Response.json(
      {
        message: "Erro inesperado",
        code: "UNEXPECTED_FAILURE",
      },
      { status: 500 },
    );
  }
}
```

---

# 16. Compliance Checklist

- [ ] Pages não possuem regra de negócio.
- [ ] Services trafegam apenas Contracts.
- [ ] Route Handlers são Input Adapters.
- [ ] Route Handlers chamam Input Ports.
- [ ] Use Cases não dependem de Next.js.
- [ ] Output Adapters ficam fora de `app/`.
- [ ] Failures são traduzidas no Adapter.
- [ ] `"use client"` usado apenas quando necessário.

---

# 17. AI Interpretation

Ao implementar Blueprint com Next.js, o agente deve concluir que:

- `app/api` materializa Input Adapters.
- `page.tsx` materializa UI Adapters.
- Next.js não define arquitetura.
- Route Handler traduz HTTP para Application.
- Service traduz UI para HTTP.
- Use Case permanece independente de Next.js.

---

# 18. References

Este documento implementa em Next.js os conceitos definidos por:

- ES-005 — Contract Model
- ES-006 — Input Port Model
- ES-008 — Use Case Model
- ES-009 — Adapter Model
- ES-010 — Application Failure Model
- LS-001 — TypeScript Representation Standard
