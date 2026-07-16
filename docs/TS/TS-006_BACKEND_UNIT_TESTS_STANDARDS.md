---
type: TechnologyStandard
title: "TS-006 — Backend Unit Testing Standard"
description: "Como testar unidades de back-end em projetos Blueprint sem acoplar testes a frameworks, banco de dados ou infraestrutura real?"
tags: [TS-006_BACKEND_UNIT_TESTS_STANDARDS]
timestamp: "2026-07-04T12:02:32Z"
---

# TS-006 — Backend Unit Testing Standard

> **Technology Standard**

| Campo          | Valor                                                              |
| -------------- | ------------------------------------------------------------------ |
| **ID**         | TS-006                                                             |
| **Título**     | Backend Unit Testing Standard                                      |
| **Versão**     | 1.0.0                                                              |
| **Status**     | Approved                                                           |
| **Tecnologia** | TypeScript Test Runner                                             |
| **Aplica-se**  | Testes unitários de Application, Domain, Ports e Adapters isolados |
| **Depende de** | ES-003, ES-004, ES-007, ES-008, ES-010, LS-001                     |

---

# 1. Technology Question

Como testar unidades de back-end em projetos Blueprint sem acoplar testes a frameworks, banco de dados ou infraestrutura real?

---

# 2. Purpose

Este documento define o padrão para testes unitários de back-end.

Testes unitários de back-end devem validar comportamento isolado de:

- Domain;
- Use Cases;
- Application Failures;
- Mappers;
- Adapters isolados quando possível.

Testes unitários não devem depender de:

- banco real;
- rede;
- sistema de arquivos;
- framework web;
- autenticação real;
- serviços externos.

---

# 3. Testing Scope

## Deve testar

- regras do Domain;
- execução de Use Cases;
- chamadas para Output Ports;
- falhas esperadas;
- tradução feita por Mappers;
- regras de autorização de aplicação.

---

## Não deve testar

- ORM real;
- banco real;
- rotas HTTP reais;
- componentes visuais;
- integração entre camadas;
- comportamento do framework.

Esses itens pertencem a testes de integração ou E2E.

---

# 4. Recommended Tooling

Para projetos TypeScript, usar preferencialmente:

```text
Vitest
```

Motivos:

- rápido;
- simples;
- compatível com TypeScript;
- boa API de mocks;
- boa integração com Vite/Next.js.

---

# 5. File Naming

Arquivos de teste unitário devem usar:

```text
*.spec.ts
```

Exemplos:

```text
create-aluno.usecase.spec.ts
aluno.spec.ts
aluno-http.mapper.spec.ts
```

---

# 6. Test Location

Testes devem ficar próximos da unidade testada.

```text
core/
└── useCases/
    └── aluno/
        ├── create-aluno.usecase.ts
        └── create-aluno.usecase.spec.ts
```

Para testes compartilhados:

```text
tests/
└── builders/
```

---

# 7. Use Case Test Pattern

Use Cases devem ser testados com Output Ports falsos.

Nunca usar banco real.

```ts
import { describe, expect, it, vi } from "vitest";

import { CreateAlunoUseCase } from "./create-aluno.usecase";

import type { AlunoRepositoryPort } from "@/core/ports/out/aluno-repository.port";

describe("CreateAlunoUseCase", () => {
  it("cria aluno quando CPF ainda não existe", async () => {
    const alunoRepository: AlunoRepositoryPort = {
      findByCpf: vi.fn().mockResolvedValue(null),
      save: vi.fn().mockImplementation(async (aluno) => aluno),
    };

    const useCase = new CreateAlunoUseCase(alunoRepository);

    const result = await useCase.execute({
      nome: "Maria Silva",
      cpf: "12345678900",
    });

    expect(result.nome).toBe("Maria Silva");
    expect(alunoRepository.findByCpf).toHaveBeenCalledWith("12345678900");
    expect(alunoRepository.save).toHaveBeenCalledOnce();
  });
});
```

---

# 8. Failure Test Pattern

Application Failures devem ser testadas explicitamente.

```ts
import { describe, expect, it, vi } from "vitest";

import { CreateAlunoUseCase } from "./create-aluno.usecase";
import { AlunoDuplicadoFailure } from "./failures/aluno-duplicado.failure";

import type { AlunoRepositoryPort } from "@/core/ports/out/aluno-repository.port";

describe("CreateAlunoUseCase", () => {
  it("falha quando CPF já está cadastrado", async () => {
    const alunoRepository: AlunoRepositoryPort = {
      findByCpf: vi.fn().mockResolvedValue({
        id: "aluno-1",
        nome: "Maria Silva",
        cpf: "12345678900",
        ativo: true,
      }),
      save: vi.fn(),
    };

    const useCase = new CreateAlunoUseCase(alunoRepository);

    await expect(
      useCase.execute({
        nome: "Maria Silva",
        cpf: "12345678900",
      }),
    ).rejects.toBeInstanceOf(AlunoDuplicadoFailure);

    expect(alunoRepository.save).not.toHaveBeenCalled();
  });
});
```

---

# 9. Domain Test Pattern

Domain deve ser testado sem mocks sempre que possível.

```ts
import { describe, expect, it } from "vitest";

import { Aluno } from "./aluno";

describe("Aluno", () => {
  it("cria aluno ativo", () => {
    const aluno = Aluno.criar({
      id: "aluno-1",
      nome: "Maria Silva",
      cpf: "12345678900",
    });

    expect(aluno.ativo).toBe(true);
    expect(aluno.nome).toBe("Maria Silva");
  });
});
```

---

# 10. Mapper Test Pattern

Mappers devem ser testados como funções puras.

```ts
import { describe, expect, it } from "vitest";

import { AlunoHttpMapper } from "./aluno-http.mapper";

describe("AlunoHttpMapper", () => {
  it("converte request em command", () => {
    const command = AlunoHttpMapper.toCreateCommand({
      nome: "Maria Silva",
      cpf: "12345678900",
    });

    expect(command).toEqual({
      nome: "Maria Silva",
      cpf: "12345678900",
    });
  });
});
```

---

# 11. Test Data Builders

Para objetos repetidos, usar builders.

```ts
export function alunoBuilder(
  overrides?: Partial<{
    id: string;
    nome: string;
    cpf: string | null;
    ativo: boolean;
  }>,
) {
  return {
    id: "aluno-1",
    nome: "Maria Silva",
    cpf: "12345678900",
    ativo: true,
    ...overrides,
  };
}
```

---

# 12. Mocking Rules

Mocks devem substituir apenas fronteiras externas.

Pode mockar:

- Output Ports;
- clock;
- uuid generator;
- email sender;
- storage;
- provider externo.

Não deve mockar:

- Domain;
- Use Case em teste;
- regras de negócio;
- mappers simples.

---

# 13. Test Naming

Nome do teste deve descrever comportamento.

Preferir:

```text
falha quando CPF já está cadastrado
```

Evitar:

```text
testa createAluno
```

---

# 14. Coverage Expectations

Cobertura mínima recomendada para back-end:

| Área           | Cobertura esperada |
| -------------- | -----------------: |
| Domain         |               Alta |
| Use Cases      |               Alta |
| Mappers        |              Média |
| Adapters       |              Média |
| Route Handlers |  Baixa em unitário |

Route Handlers devem ser cobertos preferencialmente por integração ou E2E.

---

# 15. Forbidden

É proibido em teste unitário de back-end:

- acessar banco real;
- usar Prisma real;
- chamar API externa;
- depender de Next.js;
- depender de DOM;
- testar UI;
- usar sleeps/timeouts reais;
- depender da ordem entre testes;
- compartilhar estado mutável entre testes.

---

# 16. AI Checklist

Antes de criar teste unitário de back-end, verificar:

- [ ] A unidade testada é Domain, Use Case, Mapper ou Adapter isolado?
- [ ] Output Ports foram substituídos por fakes/mocks?
- [ ] Nenhum banco real foi usado?
- [ ] Nenhum framework web foi necessário?
- [ ] Application Failures foram testadas?
- [ ] O nome do teste descreve comportamento?
- [ ] O teste é determinístico?
- [ ] O teste pode rodar isoladamente?

---

# 17. AI Interpretation

Ao implementar testes unitários de back-end, o agente deve concluir que:

- Use Cases são testados isolando Output Ports.
- Domain é testado sem mocks.
- Mappers são testados como funções puras.
- Falhas conhecidas devem ser testadas explicitamente.
- Testes unitários não validam integração com framework ou banco.
- Testes unitários devem ser rápidos, determinísticos e isolados.

---

# 18. References

Este documento implementa:

- ES-003 — Domain Model
- ES-004 — Application Model
- ES-007 — Output Port Model
- ES-008 — Use Case Model
- ES-010 — Application Failure Model
- LS-001 — TypeScript Representation Standard
