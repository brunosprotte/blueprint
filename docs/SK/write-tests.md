---
type: Skill
title: "Skill: write-tests"
description: "Se quiser rodar apenas um arquivo espec�fico:"
tags: [write-tests]
timestamp: "2026-07-04T19:34:37Z"
---

# Skill: write-tests

> Use quando precisar implementar ou validar novos testes unit�rios, de integra��o ou de componente no projeto.
> O objetivo � manter a l�gica do backend coberta com mocks e criar testes de frontend que verifiquem fluxos e valida��es, sem depender de Supabase real.

## Quando acionar esta skill

- Ao criar nova feature que envolve rota API, valida��o ou componente interativo
- Ao revisar PR: verificar se h� testes cobrindo regras de neg�cio e fluxos de usu�rio
- Em refatora��o: certificar que mudan�as n�o quebram APIs, valida��o ou formul�rios

## Ferramentas do projeto

- Jest (`v30`) como runner de teste
- `ts-jest` para compila��o TypeScript
- `jest-environment-jsdom` para testes de componentes React
- `@testing-library/react` para testes de UI e intera��es
- `jest-mock-extended` para mocks de `PrismaClient`

## Configura��o relevante

- `jest.config.js` define o ambiente padr�o como `node`
- `jest.setup.ts` inicializa mocks globais e limpa mocks entre testes
- `jest.prisma.ts` oferece `prisma` e `prismaMock` com `jest-mock-extended`

> Para testes de frontend, use `@jest-environment jsdom` no topo do arquivo ou adicione configura��o espec�fica de ambiente.

---

## 1. Padr�es de teste server-side

### 1.1. Onde escrever

- `app/api/.../route.test.ts` para APIs do App Router
- `lib/...test.ts` para fun��es utilit�rias e regras de neg�cio puras
- `app/api/.../route.ts` deve ser testada importando `GET`, `POST`, `PUT`, `DELETE` diretamente

### 1.2. Mocks e depend�ncias

- Mockar `lib/prisma` com `jest.mock(...)` e usar o `prisma` do `jest.prisma.ts`
- Mockar `lib/auth` para controlar autentica��o e autoriza��es sem chamar middleware real
- N�o testar Supabase real: sempre isolar com mocks

### 1.3. Estrutura recomendada

- `beforeEach(() => jest.clearAllMocks())`
- `const mockedPrisma = prisma as any`
- Crie um helper `createRequest(...)` para construir `Request` com m�todo, URL e JSON
- Verifique `status`, `body.success`, `body.error` e chamadas de mock

### 1.4. Exemplo de teste de rota API

```ts
/// <reference types="jest" />

import { prisma } from "../../../jest.prisma";
import { GET, POST } from "./route";

jest.mock("../../lib/prisma", () => ({ prisma }));

const mockedPrisma = prisma as any;
const baseUrl = "http://localhost:3000/api/alunos";

function createRequest(method: string, url = baseUrl, body?: unknown) {
  return new Request(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
}

describe("GET /api/alunos", () => {
  beforeEach(() => jest.clearAllMocks());

  it("retorna lista de alunos com CPF mascarado", async () => {
    mockedPrisma.aluno.findMany.mockResolvedValue([
      {
        id: "aluno-1",
        nome: "Jo�o Silva",
        cpf: "12345678901",
        codigo_aluno: "ALU-2026-0001",
        nacionalidade: "Brasileiro",
        telefone: "(11) 99999-9999",
        bairro: "Centro",
        escolaridade: "Ensino M�dio",
        data_nascimento: new Date("2000-01-01"),
        deleted_at: null,
        created_at: new Date(),
        updated_at: new Date(),
      },
    ]);

    const res = await GET(createRequest("GET"));
    expect(res.status).toBe(200);

    const body = await res.json();
    expect(body).toEqual([
      expect.objectContaining({
        nome: "Jo�o Silva",
        cpf: null,
        codigo_aluno: "ALU-2026-0001",
      }),
    ]);
    expect(mockedPrisma.aluno.findMany).toHaveBeenCalled();
  });
});

describe("POST /api/alunos", () => {
  beforeEach(() => jest.clearAllMocks());

  it("cria aluno com dados v�lidos e remove formata��o do CPF", async () => {
    mockedPrisma.aluno.create.mockResolvedValue({
      id: "aluno-1",
      nome: "Jo�o Silva",
      cpf: "12345678901",
      codigo_aluno: "ALU-2026-0001",
      nacionalidade: "Brasileiro",
      telefone: "(11) 99999-9999",
      data_nascimento: new Date("2000-01-01"),
      bairro: "Centro",
      escolaridade: "Ensino M�dio",
      deleted_at: null,
      created_at: new Date(),
      updated_at: new Date(),
    });

    const body = {
      nome: "Jo�o Silva",
      cpf: "123.456.789-01",
      codigo_aluno: "ALU-2026-0001",
      nacionalidade: "Brasileiro",
      data_nascimento: "2000-01-01",
      telefone: "(11) 99999-9999",
      bairro: "Centro",
      escolaridade: "Ensino M�dio",
    };

    const res = await POST(createRequest("POST", baseUrl, body));
    expect(res.status).toBe(201);

    const data = await res.json();
    expect(data).toEqual(
      expect.objectContaining({ nome: "Jo�o Silva", cpf: null }),
    );
    expect(mockedPrisma.aluno.create).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          cpf: "12345678901",
          codigo_aluno: "ALU-2026-0001",
          nome: "Jo�o Silva",
          nacionalidade: "Brasileiro",
        }),
      }),
    );
  });

  it("retorna 400 quando o c�digo do aluno � inv�lido", async () => {
    const body = {
      nome: "Jo�o Silva",
      cpf: "123.456.789-01",
      codigo_aluno: "INVALIDO",
      nacionalidade: "Brasileiro",
    };

    const res = await POST(createRequest("POST", baseUrl, body));
    expect(res.status).toBe(400);

    const data = await res.json();
    expect(data.error).toBe(
      "C�digo do aluno deve seguir o formato ALU-2026-0001 ou similar",
    );
    expect(mockedPrisma.aluno.create).not.toHaveBeenCalled();
  });
});
```

### 1.5. Testar erros e valida��es

- Cubra fluxos de sucesso e falha
- Verifique respostas 400/403/404/409 quando aplic�vel
- Use `jest.spyOn` ou `mockResolvedValueOnce` para simular comportamentos espec�ficos
- Em casos de rollback, assegure que o delete ou transa��o seja chamado

---

## 2. Padr�es de teste frontend

### 2.1. Onde escrever

- `app/components/*.test.tsx` para componentes reutiliz�veis
- `app/(dashboard)/**/*.test.tsx` para p�ginas e formul�rios importantes
- Use `.test.tsx` para aproveitar JSX+TS no Jest

### 2.2. Ambiente e setup

- Adicione `@jest-environment jsdom` ao topo dos testes de componente
- Importe `render`, `screen`, `fireEvent`, `waitFor` de `@testing-library/react`
- Mock `next/navigation` para evitar navega��o real
- Mock `global.fetch` quando o componente fizer chamadas de rede

### 2.3. O que focar em componentes

- Valida��o de formul�rio e mensagens de erro
- Layout condicional e estados de carregamento
- A��es do usu�rio: digitar, clicar, enviar
- Resultado ap�s submit: chamada fetch correta, navega��o, alerta ou callback

### 2.4. Exemplo de teste para `AlunoForm`

```ts
/**
 * @jest-environment jsdom
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import AlunoForm from "../aluno-form";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
}));

describe("AlunoForm", () => {
  beforeEach(() => {
    jest.resetAllMocks();
    (global.fetch as jest.Mock) = jest.fn();
  });

  it("mostra erro quando nome est� vazio", async () => {
    render(<AlunoForm />);

    fireEvent.click(screen.getByRole("button", { name: /salvar/i }));

    expect(await screen.findByText(/nome � obrigat�rio/i)).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("mostra erro quando o c�digo do aluno � inv�lido", async () => {
    render(<AlunoForm />);

    fireEvent.change(screen.getByLabelText(/nome/i), { target: { value: "Jo�o Silva" } });
    fireEvent.change(screen.getByLabelText(/c�digo do aluno/i), { target: { value: "INVALID" } });
    fireEvent.change(screen.getByLabelText(/nacionalidade/i), { target: { value: "Brasileiro" } });

    fireEvent.click(screen.getByRole("button", { name: /salvar/i }));

    expect(await screen.findByText(/c�digo do aluno deve seguir o formato/i)).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("envia payload correto para /api/alunos", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => ({}) });

    render(<AlunoForm />);
    fireEvent.change(screen.getByLabelText(/nome/i), { target: { value: "Jo�o Silva" } });
    fireEvent.change(screen.getByLabelText(/c�digo do aluno/i), { target: { value: "ALU-2026-0001" } });
    fireEvent.change(screen.getByLabelText(/nacionalidade/i), { target: { value: "Brasileiro" } });
    fireEvent.change(screen.getByLabelText(/cpf \(opcional\)/i), {
      target: { value: "123.456.789-01" },
    });

    fireEvent.click(screen.getByRole("button", { name: /salvar/i }));

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));

    expect(global.fetch).toHaveBeenCalledWith(
      "/api/alunos",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: expect.stringContaining("ALU-2026-0001"),
      }),
    );
  });
});
```

### 2.5. Exemplo de teste para `TurmaForm`

- Verificar carregamento de professores via `fetch("/api/usuarios?tipo=PROFESSOR")`
- Validar que `professorIds` atualiza ao marcar checkboxes
- Simular `POST` ou `PUT` no envio e checar o `payload`

---

## 3. Boas pr�ticas para todo o projeto

### 3.1. Organiza��o e nomenclatura

- Use `describe` para agrupar cen�rios relacionados
- Use `it` ou `test` para casos individuais
- Nomeie testes explicando o comportamento esperado
- Separe helpers locais em fun��es como `createRequest`, `buildPayload`, `renderForm`

### 3.2. Valores mockados

- Use dados representativos do dom�nio: `nome`, `periodo`, `professorIds`, `codigo_aluno`, `nacionalidade`
- Mantenha formatos iguais aos usados no c�digo real
- Simule `findMany`, `findUnique`, `create`, `update` e `delete` do Prisma

### 3.3. Cobertura m�nima sugerida

- Regras de neg�cio: 90% por fun��o
- Valida��es: 100% dos branches de erro
- Componentes: cobrir fluxos principais e estados vis�veis ao usu�rio

### 3.4. O que N�O testar

- CSS, classes ou estilos
- Implementa��o interna do React (estado local sem comportamento vis�vel)
- Depend�ncias externas reais, inclusive Supabase e DB

---

## 4. Como executar testes

```bash
npx jest
npx jest --coverage
```

Se quiser rodar apenas um arquivo espec�fico:

```bash
npx jest app/api/alunos/route.test.ts
```

---

## 5. Observa��es finais

- Prefira testar `route.ts` diretamente em vez de criar um servidor HTTP
- Use mocks para isolar autentica��o e banco de dados
- Para componentes React, valide o que o usu�rio v� e faz, n�o o valor interno de estados
- Sempre execute os testes ap�s adicionar ou alterar uma rota API ou um componente de formul�rio
