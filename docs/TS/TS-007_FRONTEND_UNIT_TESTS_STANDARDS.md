---
type: TechnologyStandard
title: "TS-007 — Frontend Unit Testing Standard"
description: "Como validar o comportamento da interface de usuário em projetos Blueprint sem depender do navegador, backend ou infraestrutura?"
tags: [TS-007_FRONTEND_UNIT_TESTS_STANDARDS]
timestamp: "2026-07-04T12:05:04Z"
---

# TS-007 — Frontend Unit Testing Standard

> **Technology Standard**

| Campo          | Valor                                            |
| -------------- | ------------------------------------------------ |
| **ID**         | TS-007                                           |
| **Título**     | Frontend Unit Testing Standard                   |
| **Versão**     | 1.0.0                                            |
| **Status**     | Approved                                         |
| **Tecnologia** | React Testing Library + Vitest                   |
| **Aplica-se**  | Testes unitários e de comportamento da interface |
| **Depende de** | TS-001, TS-003, TS-004, TS-005                   |

---

# 1. Technology Question

Como validar o comportamento da interface de usuário em projetos Blueprint sem depender do navegador, backend ou infraestrutura?

---

# 2. Purpose

Este documento define o padrão para testes unitários do Frontend.

O objetivo é validar o comportamento percebido pelo usuário.

Os testes devem verificar:

- renderização;
- interação;
- feedback visual;
- integração com Services simulados;
- estados da interface.

---

# 3. Core Principle

Testes de Frontend validam comportamento.

Não validam implementação.

O teste deve responder:

> **"O usuário consegue utilizar esta funcionalidade?"**

Nunca:

> **"O componente chamou uma função interna?"**

---

# 4. Recommended Tooling

Stack recomendada.

```text
Vitest

↓

React Testing Library

↓

@testing-library/user-event
```

Evitar bibliotecas que exponham detalhes internos do React.

---

# 5. Test Scope

## Deve testar

- renderização correta;
- interação do usuário;
- estados de loading;
- mensagens de erro;
- mensagens de sucesso;
- chamadas ao Service;
- comportamento do formulário.

---

## Não deve testar

- HTML gerado;
- implementação do React Hook Form;
- funcionamento do Zod;
- comportamento interno do shadcn/ui;
- CSS;
- detalhes internos de hooks.

---

# 6. File Naming

Arquivos de teste.

```text
*.spec.tsx
```

Exemplos.

```text
login-form.spec.tsx

aluno-form.spec.tsx

presenca-table.spec.tsx
```

---

# 7. Test Location

Os testes permanecem próximos da Feature.

```text
app/
└── (dashboard)/
    └── alunos/
        ├── components/
        │   ├── aluno-form.tsx
        │   └── aluno-form.spec.tsx
```

---

# 8. Rendering Pattern

Exemplo.

```tsx
import { render, screen } from "@testing-library/react";

import { LoginForm } from "./login-form";

describe("LoginForm", () => {
  it("renderiza os campos obrigatórios", () => {
    render(<LoginForm />);

    expect(screen.getByLabelText("E-mail")).toBeInTheDocument();

    expect(screen.getByLabelText("Senha")).toBeInTheDocument();

    expect(
      screen.getByRole("button", {
        name: /entrar/i,
      }),
    ).toBeInTheDocument();
  });
});
```

---

# 9. Interaction Pattern

Interações devem utilizar `user-event`.

```tsx
import userEvent from "@testing-library/user-event";

it("permite preencher o formulário", async () => {
  const user = userEvent.setup();

  render(<LoginForm />);

  await user.type(screen.getByLabelText("E-mail"), "usuario@email.com");

  await user.type(screen.getByLabelText("Senha"), "123456");

  expect(screen.getByDisplayValue("usuario@email.com")).toBeInTheDocument();
});
```

Nunca alterar valores diretamente.

---

# 10. Service Mocking

A UI nunca acessa HTTP real.

Mockar apenas Services.

```tsx
vi.mock("@/services/auth.service", () => ({
  authService: {
    login: vi.fn(),
  },
}));
```

---

# 11. Submit Pattern

```tsx
it("envia o formulário", async () => {
  const user = userEvent.setup();

  render(<LoginForm />);

  await user.type(screen.getByLabelText("E-mail"), "admin@email.com");

  await user.type(screen.getByLabelText("Senha"), "123456");

  await user.click(
    screen.getByRole("button", {
      name: /entrar/i,
    }),
  );

  expect(authService.login).toHaveBeenCalledOnce();
});
```

---

# 12. Validation Pattern

Validação deve ser observada pela interface.

Nunca testar Zod diretamente.

```tsx
it("exibe mensagem quando nome é obrigatório", async () => {
  const user = userEvent.setup();

  render(<AlunoForm />);

  await user.click(
    screen.getByRole("button", {
      name: /salvar/i,
    }),
  );

  expect(screen.getByText("Nome é obrigatório.")).toBeVisible();
});
```

---

# 13. Loading Pattern

```tsx
expect(button).toBeDisabled();

expect(screen.getByText("Salvando...")).toBeVisible();
```

---

# 14. Success Pattern

```tsx
expect(toast.success).toHaveBeenCalled();
```

---

# 15. Failure Pattern

```tsx
expect(screen.getByText("Não foi possível salvar.")).toBeVisible();
```

---

# 16. Accessibility

Priorizar consultas acessíveis.

Preferir.

```tsx
getByRole();

getByLabelText();

getByPlaceholderText();
```

Evitar.

```tsx
querySelector();

getByTestId();
```

`data-testid` deve ser usado apenas quando não existir alternativa acessível.

---

# 17. Mocking Rules

Pode mockar.

- Services;
- Router;
- Toast;
- Browser APIs.

Não mockar.

- React Hook Form;
- Zod;
- shadcn/ui;
- Componente em teste.

---

# 18. Coverage Expectations

Cobertura recomendada.

| Área                  | Cobertura |
| --------------------- | --------- |
| Forms                 | Alta      |
| Components de Feature | Alta      |
| Layout                | Baixa     |
| Components do shadcn  | Nenhuma   |

Componentes da biblioteca não devem ser testados.

---

# 19. Forbidden

É proibido.

- testar implementação interna;
- testar estados privados;
- testar hooks do React;
- mockar o componente em teste;
- usar `querySelector`;
- acessar DOM manualmente;
- chamar Services reais.

---

# 20. AI Checklist

Antes de criar testes Frontend.

- [ ] O teste representa comportamento do usuário?
- [ ] O Service foi mockado?
- [ ] Nenhum HTTP real foi utilizado?
- [ ] Foram usadas queries acessíveis?
- [ ] O formulário foi preenchido com `user-event`?
- [ ] Loading foi validado?
- [ ] Mensagens de erro foram verificadas?
- [ ] Mensagens de sucesso foram verificadas?
- [ ] O teste continua válido mesmo após refatoração interna?

---

# 21. AI Interpretation

Ao implementar testes Frontend, o agente deve concluir que:

- a interface é validada pelo comportamento percebido pelo usuário;
- Services representam a fronteira da aplicação e podem ser simulados;
- bibliotecas consolidadas (React Hook Form, Zod e shadcn/ui) não devem ser testadas diretamente;
- testes devem permanecer resilientes a refatorações internas;
- acessibilidade deve orientar a forma de localizar elementos.

---

# 22. References

Este documento implementa:

- TS-001 — Next.js Standard
- TS-003 — Zod Validation Standard
- TS-004 — React Hook Form Standard
- TS-005 — Shadcn/UI Standard
