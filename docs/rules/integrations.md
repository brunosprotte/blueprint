# Regras de Integra��o - Supabase, Auth e servi�os externos

> Carregar quando trabalhar com integra��o externa (email, upload, webhook, Supabase). N�o carregar para l�gica interna ou banco local.

## Stack de Servi�os Externos

| Servi�o | Uso | Pacote | Configura��o env |
|---------|-----|--------|-----------------|
| Supabase Auth | Login, JWT, recupera��o de senha | `@supabase/ssr` | `NEXT_PUBLIC_SUPABASE_URL` |
| Supabase Storage | Upload de fotos/documentos (futuro) | `@supabase/storage-js` | Same as DB URL |
| Zod | Valida��o de entrada do usu�rio | `zod` | Nenhuma necess�ria |
| Email | Notifica��es de recupera��o de conta | N/A (por enquanto) | Supabase auth email template |

## Supabase Auth

### Configura��o (`lib/supabase/server.ts`)
```ts
import { createServerClient, type CookieOptions } from '@supabase/ssr';
import { cookies } from 'next/headers';

export async function createClient() {
  const cookieStore = await cookies();
  
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        get(name) { return cookieStore.get(name)?.value; },
        set(name, value, options) {
          cookieStore.set({ name, value, ...options });
        },
        remove(name, options) {
          cookieStore.set({ name, value: '', ...options });
        },
      },
    }
  );
}
```

### Protegendo rotas (Middleware)
No `middleware.ts` na raiz do projeto:

```ts
import { createServerClient } from '@supabase/ssr';
import { NextResponse } from 'next/server';

export async function middleware(request: Request) {
  let response = NextResponse.next();
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    { cookies: /* ... */ } // cookie handler customizado
  );

  const { data: { session } } = await supabase.auth.getSession();
  
  // Rotas protegidas (dentro de /dashboard)
  if (!session && request.url.includes('/dashboard')) {
    return NextResponse.redirect(new URL('/login', request.url));
  }

  response = NextResponse.next();
  return response;
}

// Define quais rotas o middleware intercepta
export const config = { matcher: ['/((?!.*\\.|_next).*)', '/', '/(api|trpc)(.*)'] };
```

### Middleware.ts ? Regras obrigat�rias
- Sempre verificar se `session` existe ANTES de qualquer processamento de rotas protegidas
- Nunca deixar cookies ou tokens sens�veis expostos ao cliente (NUNCA ler token em client-side componente)
- O middleware N�O deve bloquear `/auth/*`, `/login`, nem assets est�ticos (.png, .js, etc.)

## Upload de Arquivos (Futuro � Storage)

```ts
// app/(dashboard)/alunos/[id]/upload-imagem/page.tsx ? Client component
  
  const { error } = await supabase.storage
    .from('fotos-alunos') // bucket j� criado no Supabase
    .upload(`aluno/${arquivo.id}/${arquivo.name}`, arquivoRef);
```

### Regras de Upload (quando implementado)
- Validar extens�o e tamanho DOIS VEZES: Zod + valida��o do storage bucket do Supabase
- Nunca armazenar arquivos em vari�veis de ambiente ou no c�digo
- Nome de caminho sempre baseado em ID, nunca nome original do arquivo

## Email (por enquanto = zero configura��o)

O sistema N�O implementa envio de email customizado. Utiliza-se **apenas** a funcionalidade padr�o de recupera��o de senha do Supabase Auth. 

Se no futuro for preciso enviar emails personalizados (ex: notifica��es), usar templates HTML simples com Tailwind inline (para compatibilidade de clientes de email) e o servi�o **SendGrid** ou **Resend**.

## Webhooks (futuro)

Neste momento, n�o h� webhooks implementados. Quando implementado:
- Usar `route.ts` em `POST api/webhook/...` para receber eventos externos
- Validar assinatura do provider via header de requisi��o (`X-Signature`)
- Responder com `200 OK` o mais r�pido poss�vel ap�s processamento

---

## Checklist Antecipado de Integra��o

- [ ] Todas vari�veis de ambiente t�m fallback no c�digo (nunca crash por undefined)
- [ ] Chaves do Supabase NUNCA expostas em client-side components ou git
- [ ] Middleware protege rotas internas corretamente
- [ ] Zod valida��o � duplamente aplicada se dados v�m de API externa
- [ ] Tratamento de falhas no auth: quando Supabase down, o app exibe mensagem amig�vel

---

## Arquivos que voc� DEVE carregar para integra��es externas

| Situa��o | Documento obrigat�rio |
|----------|----------------------|
| Configura��o de Auth/Supabase | `lib/supabase/server.ts` (ou similar no projeto) |
| Prote��o de rotas | `middleware.ts` da raiz do projeto |
| Criar nova API externa | Este arquivo (`integrogrations.md`) |
