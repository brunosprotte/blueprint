---
type: TechnologyStandard
title: "TS-003 — Zod Validation Standard"
description: "Como implementar validação estrutural usando Zod sem violar a arquitetura do Blueprint?"
tags: [TS-003_ZOD_VALIDATION_STANDARDS]
timestamp: "2026-07-04T20:02:20Z"
---

# TS-003 — Zod Validation Standard

> **Technology Standard**

| Campo          | Valor                                |
| -------------- | ------------------------------------ |
| **ID**         | TS-003                               |
| **Título**     | Zod Validation Standard              |
| **Versão**     | 1.0.0                                |
| **Status**     | Approved                             |
| **Tecnologia** | Zod                                  |
| **Aplica-se**  | Projetos Blueprint usando TypeScript |
| **Depende de** | ES-005, ES-009, ES-010, LS-001       |

---

# 1. Technology Question

Como implementar validação estrutural usando Zod sem violar a arquitetura do Blueprint?

---

# 2. Purpose

Este documento define como Zod deve ser utilizado.

Zod implementa validação estrutural.

Zod não define regras de negócio.

Zod não substitui Domain.

Zod não substitui Use Cases.

---

# 3. Technology Mapping

| Blueprint          | Zod                     |
| ------------------ | ----------------------- |
| Contract           | Schema                  |
| Validation Failure | Parse Error traduzido   |
| Input Adapter      | Local de validação      |
| Form Adapter       | Validação de formulário |
| Business Failure   | Não pertence ao Zod     |

---

# 4. Validation Boundaries

Zod deve ser usado em fronteiras de entrada.

Uso recomendado:

- Route Handler;
- formulário;
- importação de dados;
- payload externo;
- mensagens externas.

Zod não deve ser usado para implementar regra de negócio.

---

# 5. Contract Schema

Todo Request Contract deve possuir schema Zod correspondente.

```ts
import { z } from "zod";

export const createAlunoSchema = z.object({
  nome: z.string().min(3, "Nome deve ter pelo menos 3 caracteres."),
  cpf: z.string().optional(),
});

export type CreateAlunoRequest = z.infer<typeof createAlunoSchema>;
```

Regra:

- schema e contract devem nascer juntos;
- o tipo do contract deve ser inferido do schema;
- não duplicar tipo manualmente quando houver schema.

---

# 6. File Naming

Schemas devem usar:

```text
<action>-<entity>.schema.ts
```

Exemplos:

```text
create-aluno.schema.ts
update-aluno.schema.ts
registrar-presenca.schema.ts
```

---

# 7. Folder Structure

Schemas pertencem aos Contracts.

```text
core/
└── contracts/
    └── aluno/
        ├── create-aluno.schema.ts
        ├── create-aluno.request.ts
        └── create-aluno.response.ts
```

---

# 8. Route Handler Validation

Route Handlers devem validar entrada antes de chamar Input Port.

```ts
const body = await request.json();

const parseResult = createAlunoSchema.safeParse(body);

if (!parseResult.success) {
  return ApiResponse.validationFailure(parseResult.error);
}

const command = AlunoHttpMapper.toCreateCommand(parseResult.data);
```

Nunca usar cast direto:

```ts
const body = (await request.json()) as CreateAlunoRequest;
```

---

# 9. Form Validation

Formulários devem reutilizar o mesmo schema do Contract sempre que possível.

```ts
import { createAlunoSchema } from "@/core/contracts/aluno/create-aluno.schema";

const form = useForm<CreateAlunoRequest>({
  resolver: zodResolver(createAlunoSchema),
});
```

---

# 10. Business Rules

Zod valida estrutura.

Use Case valida regra de negócio.

Exemplos de Zod:

- campo obrigatório;
- tamanho mínimo;
- formato;
- tipo;
- enum;
- string vazia;
- número mínimo.

Exemplos de Use Case:

- CPF duplicado;
- aluno matriculado na turma;
- presença já registrada;
- professor responsável pela turma;
- aula aberta para presença.

---

# 11. Validation Failure Translation

Erros de Zod devem ser traduzidos para Validation Failure.

Nunca expor detalhes crus sem normalização.

Formato recomendado:

```ts
export type FieldValidationIssue = {
  readonly field: string;
  readonly message: string;
};
```

```ts
export type ValidationFailureResponse = {
  readonly code: "VALIDATION_FAILURE";
  readonly message: string;
  readonly issues: readonly FieldValidationIssue[];
};
```

---

# 12. ApiResponse Validation Example

```ts
import { ZodError } from "zod";

export class ApiResponse {
  static validationFailure(error: ZodError): Response {
    return Response.json(
      {
        code: "VALIDATION_FAILURE",
        message: "Dados inválidos.",
        issues: error.issues.map((issue) => ({
          field: issue.path.join("."),
          message: issue.message,
        })),
      },
      { status: 422 },
    );
  }
}
```

---

# 13. Form Error Mapping

O formulário deve exibir erros por campo.

```tsx
<FormField
  control={form.control}
  name="nome"
  render={({ field }) => (
    <FormItem>
      <FormLabel>Nome</FormLabel>
      <FormControl>
        <Input {...field} />
      </FormControl>
      <FormMessage />
    </FormItem>
  )}
/>
```

---

# 14. Schema Composition

Schemas comuns devem ser reutilizados.

```ts
export const cpfSchema = z
  .string()
  .min(11, "CPF inválido.")
  .max(14, "CPF inválido.");
```

```ts
export const createAlunoSchema = z.object({
  nome: nomeSchema,
  cpf: cpfSchema.optional(),
});
```

---

# 15. Forbidden

É proibido:

- duplicar tipo do request manualmente quando há schema;
- usar Zod dentro do Domain;
- usar Zod dentro do Use Case para regra de negócio;
- usar cast direto após `request.json`;
- retornar `ZodError` cru para o cliente;
- criar schema local dentro de componente quando já existe Contract Schema.

---

# 16. AI Checklist

Antes de criar uma entrada validável, verificar:

- [ ] Existe Request Contract?
- [ ] Existe Schema Zod?
- [ ] O Request é inferido do Schema?
- [ ] O Route Handler usa `safeParse`?
- [ ] O formulário reutiliza o Schema?
- [ ] Zod ficou fora do Domain?
- [ ] Zod ficou fora do Use Case?
- [ ] Erros são traduzidos para Validation Failure?
- [ ] Não existe cast direto de request?

---

# 17. AI Interpretation

Ao implementar validação com Zod, o agente deve concluir que:

- Zod valida fronteiras de entrada.
- Zod representa validação estrutural.
- Zod não implementa regra de negócio.
- Schemas pertencem aos Contracts.
- Use Cases continuam responsáveis por regra de negócio.
- Validation Failures devem ser traduzidas no Adapter.

---

# 18. References

Este documento implementa:

- ES-005 — Contract Model
- ES-009 — Adapter Model
- ES-010 — Application Failure Model
- LS-001 — TypeScript Representation Standard
