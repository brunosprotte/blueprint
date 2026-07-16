---
type: Skill
title: Cypress Testing Guide
description: "Testes e2e/integração. Real scenarios. Project-specific."
tags: [write-tests-cypress]
timestamp: "2026-07-04T19:30:00Z"
---

# Cypress Testing Guide

Testes e2e/integração. Real scenarios. Project-specific.

---

## 1. Setup

**Install:**

```bash
npm install -D cypress
npx cypress open
```

**Config:** `cypress.config.ts`

```typescript
import { defineConfig } from "cypress";

export default defineConfig({
  e2e: {
    baseUrl: "http://localhost:3000",
    viewportWidth: 1280,
    viewportHeight: 720,
  },
  component: {
    devServer: {
      framework: "next",
      bundler: "webpack",
    },
  },
});
```

**Env vars:** `.env.local` (test)

```
DATABASE_URL="..."
SUPABASE_URL="..."
NEXT_PUBLIC_SUPABASE_ANON_KEY="..."
```

---

## 2. Patterns

### Login Flow

```typescript
// cypress/e2e/auth.cy.ts
describe("Auth", () => {
  it("login válido", () => {
    cy.visit("/");
    cy.get('input[name="cpf"]').type("prof@escola.com");
    cy.get('input[name="senha"]').type("senha123");
    cy.get('button[type="submit"]').click();
    cy.url().should("include", "/dashboard");
  });

  it("CPF inválido rejeitado", () => {
    cy.visit("/");
    cy.get('input[name="cpf"]').type("invalid");
    cy.get('button[type="submit"]').click();
    cy.contains("CPF ou senha inválidos").should("be.visible");
  });
});
```

### Criar Aluno

```typescript
// cypress/e2e/alunos.cy.ts
describe("Alunos", () => {
  beforeEach(() => {
    cy.login("prof@escola.com", "senha123");
    cy.visit("/dashboard/alunos/novo");
  });

  it("criar aluno com dados válidos", () => {
    cy.get('input[name="nome"]').type("João Silva");
    cy.get('input[name="cpf"]').type("12345678901");
    cy.get('select[name="turma_id"]').select("1");
    cy.get('button[type="submit"]').click();

    cy.url().should("include", "/dashboard/alunos");
    cy.contains("Aluno criado com sucesso").should("be.visible");
  });

  it("rejeita CPF inválido", () => {
    cy.get('input[name="nome"]').type("João");
    cy.get('input[name="cpf"]').type("00000000000");
    cy.get('button[type="submit"]').click();

    cy.contains("CPF inválido").should("be.visible");
  });
});
```

### Listar Turmas + Filter

```typescript
// cypress/e2e/turmas.cy.ts
describe("Turmas", () => {
  beforeEach(() => {
    cy.login("prof@escola.com", "senha123");
  });

  it("listar turmas", () => {
    cy.visit("/dashboard/turmas");
    cy.get("table tbody tr").should("have.length.greaterThan", 0);
  });

  it("filtrar turmas por ano", () => {
    cy.visit("/dashboard/turmas");
    cy.get('select[name="ano"]').select("2024");
    cy.get("button:contains('Filtrar')").click();

    cy.get("table tbody tr").each(($row) => {
      cy.wrap($row).should("contain", "2024");
    });
  });

  it("editar turma", () => {
    cy.visit("/dashboard/turmas");
    cy.get("table tbody tr:first td:last button:first").click();
    cy.url().should("include", "/editar");

    cy.get('input[name="nome"]').clear().type("Turma 2024 (Editada)");
    cy.get('button[type="submit"]').click();
    cy.contains("Turma atualizada").should("be.visible");
  });
});
```

### Presença - Marcar/Desmarcar

```typescript
// cypress/e2e/presenca.cy.ts
describe("Presença", () => {
  beforeEach(() => {
    cy.login("prof@escola.com", "senha123");
    cy.visit("/dashboard/presencas");
  });

  it("marcar presença", () => {
    cy.get('select[name="turma_id"]').select("1");
    cy.get("button:contains('Carregar')").click();

    cy.get('input[type="checkbox"]').first().click();
    cy.get('button[type="submit"]').click();
    cy.contains("Presença registrada").should("be.visible");
  });

  it("presença persiste após reload", () => {
    cy.get('select[name="turma_id"]').select("1");
    cy.get("button:contains('Carregar')").click();
    cy.get('input[type="checkbox"]').first().click();
    cy.get('button[type="submit"]').click();

    cy.reload();
    cy.get('select[name="turma_id"]').select("1");
    cy.get("button:contains('Carregar')").click();
    cy.get('input[type="checkbox"]').first().should("be.checked");
  });

  it("desmarcar presença", () => {
    cy.get('select[name="turma_id"]').select("1");
    cy.get("button:contains('Carregar')").click();
    cy.get('input[type="checkbox"]').first().click();
    cy.get('button[type="submit"]').click();

    cy.reload();
    cy.get('select[name="turma_id"]').select("1");
    cy.get("button:contains('Carregar')").click();
    cy.get('input[type="checkbox"]').first().click();
    cy.get('button[type="submit"]').click();
    cy.contains("Presença removida").should("be.visible");
  });
});
```

---

## 3. API Mocking (Intercept)

```typescript
// Interceptar criação aluno
cy.intercept("POST", "/api/alunos", {
  statusCode: 201,
  body: {
    id: "123",
    nome: "João",
    cpf: "12345678901",
  },
}).as("createAluno");

cy.get('button[type="submit"]').click();
cy.wait("@createAluno").then((interception) => {
  expect(interception.request.body).to.deep.include({
    nome: "João",
    cpf: "12345678901",
  });
});
```

---

## 4. Custom Commands

**`cypress/support/commands.ts`**

```typescript
Cypress.Commands.add("login", (cpf: string, senha: string) => {
  cy.visit("/");
  cy.get('input[name="cpf"]').type(cpf);
  cy.get('input[name="senha"]').type(senha);
  cy.get('button[type="submit"]').click();
  cy.url().should("include", "/dashboard");
});

Cypress.Commands.add("createAluno", (dados: any) => {
  cy.visit("/dashboard/alunos/novo");
  cy.get('input[name="nome"]').type(dados.nome);
  cy.get('input[name="cpf"]').type(dados.cpf);
  cy.get('button[type="submit"]').click();
});
```

**Usage:**

```typescript
cy.login("prof@escola.com", "senha123");
cy.createAluno({
  nome: "João",
  cpf: "12345678901",
});
```

---

## 5. Best Practices

- **Selectors:** `data-testid` > name > class. Evita quebrar com CSS.
- **Waits:** Implicit (cy.get). Evita cy.wait(5000).
- **Isolation:** Cada teste independente. beforeEach setup.
- **Assertions:** cy.should("be.visible"), cy.url().should("include", "/path")
- **Cleanup:** afterEach pra logout/reset se needed.

---

## 6. Run

**UI:**

```bash
npm run cypress:open
```

**Headless (CI):**

```bash
npm run cypress:run
```

**Spec específica:**

```bash
cypress run --spec "cypress/e2e/alunos.cy.ts"
```
