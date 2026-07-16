# Regras de Testes - Sistema de Gest�o de Cursos

> Carregar ao implementar novas features ou refatorar l�gica. Define os tipos, ferramentas e padr�es de teste do projeto.

## Stack de Testes

| Camada | Ferramenta | Arquivo de Config | Quando usar |
|--------|-----------|-------------------|------------|
| Unit Testing | Jest (`v30+`) | `jest.config.js` | Regras de neg�cio puras, formata��es, valida��o Zod |
| Integration Tests | Jest + Fetch (App Router) | `jest.config.js` | Rotas API, Server Actions, middleware |
| Component Test | Jest + React Testing Library | `@testing-library/react` | Client components, hooks customizados, UI interativa |

## Padr�es de Organiza��o

### 1. Unit Tests (`lib/`)
L�gica pura deve ter cobertura m�xima. Sempre testar casos de borda (nulls e strings vazias).

```ts
// lib/calculos.test.ts
import { calcularAprovacao } from './calculos';
import { describe, it, expect } from '@jest/globals';

describe('calcularAprovacao', () => {
  it('aprova aluno com frequencia e nota suficientes', () => {
    const resultado = calcularAprovacao(80, 6.5);
    expect(resultado).toBe(true);
  });

  it('reprova por nota (mesmo com frequencia OK)', () => {
    expect(calcularAprovacao(90, 4.5)).toBe(false);
  });
});
```

### 2. Rotas e APIs (`app/api/` ou `app/[pasta]/route.tsx`)
Usar a fun��o `fetch` do Jest (native no runtime do Node) para simular requisi��es HTTP externas na aplica��o:

```ts
// app/api/alunos/route.test.ts
import { POST, GET } from './route'; // importar as rotas diretamente!

describe('GET /api/alunos', () => {
  it('retorna lista de alunos formatados', async () => {
    const response = await GET();
    expect(response.status).toBe(200);
    const json = await response.json();
    expect(Array.isArray(json)).toBeTruthy();
  });
});
```

### 3. Server Actions (dentro do Componente)
Para testar server actions, importar a fun��o e chamar diretamente:

```ts
// app/(dashboard)/alunos/novo/page.test.tsx
import { criarAlunoAction } from './actions'; // onde a action est� definida

test('valida email duplicado', async () => {
  await expect(criarAlunoAction({ email: 'ja@existe.com' }))
    .rejects.toThrow('Email j� cadastrado');
});
```

## Mockagem de Banco e Supabase

### Supabase Client (`lib/supabase.ts`)
Sempre mockar o cliente supabase para n�o tocar na DB real nos testes:

```ts
// __mocks__/supabase.ts (ou dentro do setupFilesAfterEnv)
import { createClient } from '@supabase/ssr';
export default { auth:... }; // Mock manual da inst�ncia

// No teste:
vi.mock('@/lib/supabase', () => ({
  createServerClient: vi.fn(() => ({...}))
}));
```

### Prisma Client (`lib/prisma.ts`)
Usar `prisma.$disconnect()` em cada `afterEach` para evitar vazamento de conex�es. Mocking de resultados:
1. Usar `@prisma/client/mock` se dispon�vel, ou objetos plain JSON retornando as estruturas que o schema espera.

## Regras Cr�ticas de Qualidade

1. **NUNCA** rodar testes contra a DB real (Supabase) em CI/pipeline local � usar mocks
2. Todo Zod Schema tem seu pr�prio arquivo de teste (.test.ts na mesma pasta)
3. Cobertura m�nima de regra de neg�cio: 90%. Regras como `calcularFrequencia` s�o cr�ticas e devem ter todos os casos cobertos (75%, limiares, NaN)
4. Testes de UI: focar em intera��es (`fireEvent`, `userEvent`) n�o em implementa��o interna do React

## Regras de Teste para APIs e Dados Sens�veis

### 1. Autentica��o Obrigat�ria
```ts
// Sempre testar que rota rejeita requests sem auth
describe('POST /api/alunos', () => {
  it('retorna 403 sem autentica��o', async () => {
    const response = await POST(new Request(...));
    expect(response.status).toBe(403);
  });

  it('retorna 403 com role insuficiente', async () => {
    // Mock user como ALUNO, n�o PROFESSOR
    const response = await POST(requestComAuthALUNO);
    expect(response.status).toBe(403);
  });
});
```

### 2. Valida��o Completa de Entrada
```ts
// CPF: sempre testar d�gitos verificadores
describe('POST /api/alunos - CPF', () => {
  it('rejeita CPF com d�gitos verificadores inv�lidos', async () => {
    const response = await POST(req({ cpf: '11111111111' }));
    const json = await response.json();
    expect(json.error).toContain('CPF inv�lido');
  });

  it('aceita CPF formatado ou limpo', async () => {
    const res1 = await POST(req({ cpf: '123.456.789-09' }));
    const res2 = await POST(req({ cpf: '12345678909' }));
    expect(res1.status).toBe(201);
    expect(res2.status).toBe(201);
  });

  it('rejeita tamanho inv�lido', async () => {
    expect(await POST(req({ cpf: '12345' }))).toHaveStatus(400);
  });
});

// C�digo aluno: sempre testar formato ALU-YYYY-NNNN
describe('POST /api/alunos - C�digo', () => {
  it('aceita formato ALU-2026-0001', async () => {
    expect(await POST(req({ codigo_aluno: 'ALU-2026-0001' }))).toHaveStatus(201);
  });

  it('rejeita formatos: ALU-26-1, alu-2026-1, 2026-0001', async () => {
    expect(await POST(req({ codigo_aluno: 'ALU-26-1' }))).toHaveStatus(400);
  });

  it('converte para mai�sculas', async () => {
    // Verificar que backend aceita 'alu-2026-0001' e persiste como 'ALU-2026-0001'
  });
});
```

### 3. Dados Sens�veis Nunca na Response
```ts
// CPF NUNCA deve ser retornado
describe('POST /api/alunos - Masking', () => {
  it('retorna cpf: null mesmo que enviado', async () => {
    const response = await POST(req({ cpf: '12345678909' }));
    const json = await response.json();
    expect(json.cpf).toBeNull();
  });

  it('GET /api/alunos nunca exp�e CPF', async () => {
    const response = await GET();
    const alunos = await response.json();
    alunos.forEach(aluno => {
      expect(aluno.cpf).toBeNull();
    });
  });
});
```

### 4. Erro Mapping Prisma
```ts
describe('POST /api/alunos - Error Handling', () => {
  it('P2002 (duplicada) retorna 409', async () => {
    // Simulate codigo_aluno duplicado
    expect(await POST(req1)).toHaveStatus(201);
    expect(await POST(req2WithSameCodigo)).toHaveStatus(409);
  });

  it('mensagem de erro n�o exp�e schema interno', async () => {
    const res = await POST(req({ cpf: 'invalid' }));
    const json = await response.json();
    expect(json.error).not.toContain('Prisma');
    expect(json.error).not.toContain('sql');
  });
});
```

### 5. Pagina��o Obrigat�ria
```ts
describe('GET /api/alunos - Pagination', () => {
  it('retorna { data, page, limit, hasMore }', async () => {
    const res = await GET();
    const json = await res.json();
    expect(json).toHaveProperty('data');
    expect(json).toHaveProperty('page');
    expect(json).toHaveProperty('limit');
    expect(json).toHaveProperty('hasMore');
  });

  it('skip funciona: page=2 retorna registros diferentes de page=1', async () => {
    const page1 = await GET('?page=1');
    const page2 = await GET('?page=2');
    const data1 = await page1.json();
    const data2 = await page2.json();
    expect(data1.data[0].id).not.toEqual(data2.data[0].id);
  });
});
```

### 6. Testes E2E (Cypress)
```ts
// cypress/e2e/alunos-cadastro.cy.ts
describe('Cadastro Aluno - E2E', () => {
  // Testes de seguran�a/valida��o iguais aos de backend
  it('N�o deixar enviador formul�rio sem campos obrigat�rios');
  it('Mascarar CPF no input automaticamente');
  it('Rejeitar c�digo do aluno com formato inv�lido');
});
```

## Checklist de Teste para Nova API

- [ ] Auth check: 403 sem user/role adequado
- [ ] Input validation: tipo, tamanho, formato, d�gitos verificadores
- [ ] CPF/Sens�vel: teste que nunca retorna na response
- [ ] Error mapping: Prisma ? HTTP status correto
- [ ] Pagina��o: skip + limit + metadados
- [ ] Duplica��o: 409 on existing `@unique` field
- [ ] Soft delete: `deleted_at` filtrado em SELECTs
- [ ] Unit tests: fun��es de valida��o isoladas
- [ ] Integration tests: fluxo completo (create ? read ? update ? delete)
- [ ] E2E tests: Cypress com intera��es reais

## Arquivos que voc� DEVE consultar para testes

| Situa��o | Consulta obrigat�ria |
|----------|-------------------|
| Escrever teste de regra de neg�cio | `CONFIGURACAO.md` (regras validas) e `lib/calculos.ts` | 
| Criar mock de API | `app/api/[nome]/route.ts` (copia da assinatura real) |
| Implementar API nova | `docs/rules/architecture.md` - Checklist de Seguran�a para Rotas API |
| Testar dados sens�veis | `CODE_REVIEW_ALUNOS_API.md` - Se��o "Sem valida��o de d�gitos verificadores CPF" |
