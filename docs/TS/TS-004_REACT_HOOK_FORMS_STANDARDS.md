---
type: TechnologyStandard
title: "TS-004 � React Hook Form Standard"
description: "Como gerenciar o ciclo de vida de formul�rios utilizando React Hook Form preservando a arquitetura do Blueprint?"
tags: [TS-004_REACT_HOOK_FORMS_STANDARDS]
timestamp: "2026-07-04T19:34:37Z"
---

# TS-004 � React Hook Form Standard

> **Technology Standard**

| Campo          | Valor                    |
| -------------- | ------------------------ |
| **ID**         | TS-004                   |
| **T�tulo**     | React Hook Form Standard |
| **Vers�o**     | 1.0.0                    |
| **Status**     | Approved                 |
| **Tecnologia** | React Hook Form          |
| **Aplica-se**  | Projetos React / Next.js |
| **Depende de** | TS-001, TS-003           |

---

# 1. Technology Question

Como gerenciar o ciclo de vida de formul�rios utilizando React Hook Form preservando a arquitetura do Blueprint?

---

# 2. Purpose

Este documento define como React Hook Form deve ser utilizado.

React Hook Form � respons�vel exclusivamente pelo gerenciamento do estado do formul�rio.

Inclui:

- estado;
- submiss�o;
- reset;
- valida��o integrada;
- gerenciamento de erros;
- integra��o com componentes da interface.

React Hook Form n�o implementa:

- regras de neg�cio;
- persist�ncia;
- chamadas HTTP;
- valida��o estrutural;
- componentes visuais.

---

# 3. Technology Mapping

| Blueprint              | React Hook Form    |
| ---------------------- | ------------------ |
| Form State             | `useForm()`        |
| Form Context           | `FormProvider`     |
| Submission             | `handleSubmit()`   |
| Validation Integration | `resolver`         |
| Form Errors            | `formState.errors` |
| Dynamic Collections    | `useFieldArray()`  |
| Reset                  | `reset()`          |

---

# 4. Form Lifecycle

Todo formul�rio deve seguir o ciclo abaixo.

```text
Inicializa��o

?

Intera��o do Usu�rio

?

Valida��o

?

Submiss�o

?

Resposta

?

Reset ou Atualiza��o
```

Cada etapa possui responsabilidade espec�fica.

---

# 5. Form Initialization

Todo formul�rio deve iniciar utilizando `useForm`.

Exemplo.

```tsx
const form = useForm<CreateAlunoRequest>({
  resolver: zodResolver(createAlunoSchema),
  defaultValues: {
    nome: "",
    cpf: "",
  },
});
```

O estado inicial deve representar um formul�rio v�lido para edi��o.

---

# 6. Validation Integration

React Hook Form n�o realiza valida��o diretamente.

Toda valida��o estrutural deve ser delegada ao TS-003.

Exemplo.

```tsx
resolver: zodResolver(createAlunoSchema);
```

Nunca implementar valida��o manual utilizando eventos do formul�rio.

---

# 7. Submission

A submiss�o deve ocorrer exclusivamente atrav�s de `handleSubmit`.

```tsx
const onSubmit = form.handleSubmit(async (values) => {
  await alunoService.criar(values);
});
```

Nunca utilizar `onClick` como mecanismo principal de submiss�o.

---

# 8. Service Integration

O formul�rio comunica-se apenas com Services.

Fluxo recomendado.

```text
Form

?

Service

?

Route Handler

?

Application
```

O formul�rio nunca acessa:

- banco de dados;
- Use Cases;
- Output Ports.

---

# 9. Loading State

Durante opera��es ass�ncronas deve existir indica��o visual.

Exemplo.

```tsx
<Button type="submit" disabled={form.formState.isSubmitting}>
  Salvar
</Button>
```

O estado de carregamento deve impedir submiss�es duplicadas.

---

# 10. Error Handling

Erros de valida��o devem ser apresentados atrav�s de `formState.errors`.

Erros de neg�cio devem ser traduzidos pelo Service e apresentados pela interface.

Nunca misturar erros estruturais com regras de neg�cio.

---

# 11. Reset Strategy

Ap�s uma opera��o bem-sucedida, o formul�rio deve executar uma estrat�gia expl�cita.

Exemplos.

- reset completo;
- atualiza��o parcial;
- navega��o;
- perman�ncia dos dados.

Nunca depender do comportamento padr�o do navegador.

---

# 12. Dynamic Collections

Cole��es din�micas devem utilizar `useFieldArray`.

Exemplos.

- telefones;
- respons�veis;
- disciplinas;
- anexos.

Nunca gerenciar cole��es utilizando m�ltiplos `useState`.

---

# 13. Form Context

Quando m�ltiplos componentes participarem do mesmo formul�rio, utilizar `FormProvider`.

Evitar prop drilling.

---

# 14. Component Responsibilities

React Hook Form � respons�vel apenas por:

- estado;
- eventos;
- submiss�o;
- integra��o com valida��o.

A renderiza��o pertence ao Design System.

Quando o projeto adotar shadcn/ui, a composi��o do formul�rio deve usar o wrapper oficial:

- `Form`
- `FormField`
- `FormItem`
- `FormLabel`
- `FormControl`
- `FormMessage`

O formul�rio n�o deve montar sua pr�pria estrutura visual se o wrapper do Design System j� existir.

---

# 15. Recommended Flow

```text
React Hook Form

?

Zod Resolver

?

Service

?

Route Handler

?

Application
```

Cada camada possui responsabilidade independente.

---

# 16. Forbidden

� proibido:

- utilizar `useState` para controlar campos do formul�rio;
- implementar valida��o manual;
- acessar APIs diretamente do formul�rio;
- chamar Use Cases;
- acessar banco de dados;
- utilizar m�ltiplas fontes de verdade para o mesmo campo;
- duplicar estado j� gerenciado pelo React Hook Form.

---

# 17. AI Checklist

Antes de criar um formul�rio, verificar:

- [ ] Existe `useForm`?
- [ ] Existe `resolver`?
- [ ] Existe integra��o com Zod?
- [ ] Existe `handleSubmit`?
- [ ] O formul�rio comunica-se apenas com Services?
- [ ] Existe tratamento de loading?
- [ ] Existe estrat�gia expl�cita de reset?
- [ ] N�o existem `useState` desnecess�rios?
- [ ] N�o existe regra de neg�cio no formul�rio?

---

# 18. AI Interpretation

Ao implementar formul�rios utilizando React Hook Form, o agente deve concluir que:

- React Hook Form gerencia exclusivamente o ciclo de vida do formul�rio;
- valida��o estrutural pertence ao Zod;
- renderiza��o pertence ao Design System;
- regras de neg�cio permanecem na Application;
- comunica��o externa ocorre apenas atrav�s de Services;
- o formul�rio possui uma �nica fonte de verdade para seu estado.

Quando shadcn/ui estiver adotado no projeto, o formul�rio deve ser renderizado com os componentes do Design System, e n�o com HTML puro.

---

# 19. References

Este documento implementa:

- TS-001 � Next.js Standard
- TS-003 � Zod Validation Standard

� implementado por:

- TS-005 � Shadcn/UI Standard
