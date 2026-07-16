---
type: TechnologyStandard
title: "TS-005 — Shadcn/UI Standard"
description: "Como implementar o Design System oficial utilizando shadcn/ui preservando a arquitetura do Blueprint?"
tags: [TS-005_SHADCN_UI_STANDARDS]
timestamp: "2026-07-04T17:50:40Z"
---

# TS-005 — Shadcn/UI Standard

> **Technology Standard**

| Campo          | Valor                           |
| -------------- | ------------------------------- |
| **ID**         | TS-005                          |
| **Título**     | Shadcn/UI Standard              |
| **Versão**     | 2.0.0                           |
| **Status**     | Approved                        |
| **Tecnologia** | shadcn/ui                       |
| **Aplica-se**  | Projetos React / Next.js        |
| **Depende de** | TS-001, TS-003, TS-004, PAT-001 |

---

# 1. Technology Question

Como implementar o Design System oficial utilizando shadcn/ui preservando a arquitetura do Blueprint?

---

# 2. Purpose

Este documento define como componentes visuais devem ser implementados utilizando shadcn/ui.

O objetivo é materializar o Design System definido pelo Technology Pack.

Este documento não define:

- arquitetura;
- regras de negócio;
- validação;
- gerenciamento de estado.

Essas responsabilidades pertencem aos demais documentos do Blueprint.

---

# 3. Technology Mapping

| Blueprint            | shadcn/ui                |
| -------------------- | ------------------------ |
| Design System        | Componentes UI           |
| UI Adapter           | Componentes React        |
| Theme                | CSS Variables + Tailwind |
| Layout               | Component Composition    |
| Stable UI Identifier | `data-testid` (PAT-001)  |

---

# 4. Component Organization

Os componentes gerados pelo shadcn devem permanecer em:

```text
components/
└── ui/
```

Esses componentes representam a implementação oficial do Design System.

Não devem conter regras de negócio.

---

# 5. Feature Components

Componentes específicos da aplicação devem permanecer próximos da Feature.

```text
app/
└── (dashboard)/
    └── alunos/
        └── components/
            ├── aluno-form.tsx
            ├── aluno-table.tsx
            └── aluno-toolbar.tsx
```

A UI do domínio nunca deve ser criada dentro de `components/ui`.

---

# 6. Component Hierarchy

Formulários.

```text
Page
    ↓
Card
    ↓
CardHeader
    ↓
CardContent
    ↓
Form
    ↓
Actions
```

---

Listagens.

```text
Page
    ↓
Toolbar
    ↓
Filters
    ↓
Table
    ↓
Pagination
```

---

Confirmações.

```text
Page
    ↓
Dialog
    ↓
Actions
```

---

Feedback.

```text
Page
    ↓
Toast
```

ou

```text
Page
    ↓
Alert
```

---

# 7. Component Selection

Sempre utilizar componentes do Design System quando existir equivalente.

Em projetos Blueprint com shadcn/ui adotado, a UI de feature deve usar `components/ui` para toda composição visual de formulário, ação, feedback e navegação quando existir componente equivalente.

É proibido montar interfaces de feature com HTML puro para componentes que já existam no Design System oficial.

Exemplos.

```text
Button

Input

Textarea

Select

Checkbox

Switch

Radio Group

Card

Badge

Dialog

Dropdown Menu

Popover

Tabs

Table

Alert

Skeleton

Separator

Tooltip
```

Evitar HTML puro quando houver componente equivalente.

Quando o componente envolver formulário, usar o wrapper de React Hook Form definido pelo TS-004:

- `Form`
- `FormField`
- `FormItem`
- `FormLabel`
- `FormControl`
- `FormMessage`

---

# 8. Stable UI Identifier

Todo elemento interativo deve implementar o PAT-001.

Exemplo.

```tsx
<Input
    id="email"
    data-testid="login-email"
/>

<Button
    data-testid="login-submit"
>
    Entrar
</Button>
```

Os identificadores devem permanecer estáveis durante toda a evolução da Feature.

Nunca utilizar textos ou classes CSS como identificadores.

---

# 9. Accessibility

Todos os componentes devem preservar acessibilidade nativa.

Utilizar:

- Label associado ao campo;
- mensagens de erro acessíveis;
- foco automático quando apropriado;
- navegação por teclado;
- atributos ARIA quando necessários.

Nunca remover recursos de acessibilidade oferecidos pelo Design System.

---

# 10. Theme

A definição do tema pertence ao Technology Pack.

Este documento apenas define como consumir os tokens.

Exemplos.

```text
Tailwind Tokens

CSS Variables

Design Tokens
```

O componente nunca deve depender de cores fixas.

---

# 11. Responsive Design

Componentes devem utilizar utilitários responsivos do Tailwind.

Exemplo.

```text
sm:

md:

lg:

xl:
```

Nunca criar versões duplicadas do mesmo componente para diferentes tamanhos de tela.

---

# 12. Styling Rules

Preferir:

- classes utilitárias;
- composição de componentes;
- variantes do shadcn;
- tokens do tema.

Evitar:

- CSS customizado sem necessidade;
- estilos inline;
- duplicação de estilos.

---

# 13. Forbidden

É proibido:

- utilizar HTML puro quando existir componente equivalente;
- editar diretamente componentes gerados em `components/ui`;
- adicionar regras de negócio em componentes visuais;
- acessar banco de dados;
- chamar Use Cases;
- implementar validação manual;
- criar identificadores instáveis;
- utilizar classes CSS como seletor de testes.

---

# 14. AI Checklist

Antes de criar uma interface utilizando shadcn/ui.

- [ ] Existe componente oficial equivalente?
- [ ] O componente pertence à pasta correta?
- [ ] O PAT-001 foi implementado?
- [ ] O componente preserva acessibilidade?
- [ ] O layout segue a hierarquia recomendada?
- [ ] Os tokens do tema estão sendo utilizados?
- [ ] Não existe regra de negócio?
- [ ] Não existe acesso direto à infraestrutura?
- [ ] Não existem estilos duplicados?

---

# 15. AI Interpretation

Ao implementar interfaces utilizando shadcn/ui, o agente deve concluir que:

- shadcn/ui materializa o Design System do Technology Pack;
- componentes representam apenas interface;
- regras de negócio permanecem fora da UI;
- componentes reutilizam tokens do tema;
- todos os elementos interativos implementam o PAT-001 através de `data-testid`;
- a interface permanece desacoplada da tecnologia de testes.

Novos TSs de front-end podem complementar este padrão para tecnologias específicas, mas não substituem o uso de `components/ui` quando houver equivalente oficial.

Futuras regras de identificação de UI podem ser agrupadas em novos PATs, desde que preservem a estabilidade dos seletores de teste e não conflitem com o PAT-001 vigente.

---

# 16. References

Este documento implementa:

- TS-001 — Next.js Standard
- TS-003 — Zod Validation Standard
- TS-004 — React Hook Form Standard
- PAT-001 — Stable UI Identifier
