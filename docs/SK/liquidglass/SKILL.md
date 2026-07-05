---
name: liquid-glass-ui
description: Guia para cria��o de componentes Next.js 16 utilizando Tailwind CSS 4 seguindo a identidade visual Liquid Glass.
version: 1.0
author: OpenAI
---

# Skill: Liquid Glass UI

## Objetivo

Todo componente criado deve seguir a identidade visual **Liquid Glass**, inspirada nas interfaces modernas de vidro transl�cido.

Esta skill deve ser aplicada automaticamente sempre que forem criados:

- p�ginas
- layouts
- cards
- modais
- bot�es
- menus
- sidebars
- barras superiores
- formul�rios
- tabelas
- di�logos
- dropdowns
- componentes reutiliz�veis

O objetivo � manter consist�ncia visual em toda a aplica��o.

---

# Stack

Sempre assumir:

- Next.js 16
- React 19
- TypeScript
- Tailwind CSS 4
- App Router
- Server Components sempre que poss�vel
- Client Components apenas quando realmente necess�rio.

---

# Filosofia

A interface deve transmitir:

- eleg�ncia
- suavidade
- profundidade
- transpar�ncia
- ilumina��o
- anima��es discretas
- sensa��o de vidro l�quido

Nunca produzir interfaces totalmente opacas.

Evitar apar�ncia "Material Design".

Evitar sombras extremamente fortes.

Evitar bordas pesadas.

Evitar cores extremamente saturadas.

---

# Princ�pios Visuais

Todo componente deve possuir:

## Fundo

Utilizar fundo transl�cido.

Exemplo:

```
background:
rgba(255,255,255,0.08)
```

Nunca utilizar:

```
bg-white
```

ou

```
bg-gray-100
```

como fundo principal.

---

## Blur

Sempre utilizar backdrop blur.

Preferencialmente entre:

```
backdrop-blur-xl

ou

backdrop-blur-2xl
```

Nunca deixar um painel totalmente transparente.

---

## Bordas

As bordas devem ser suaves.

Utilizar:

```
border-white/15

ou

border-white/20
```

Nunca utilizar:

```
border-black
```

---

## Gradientes

Sempre que poss�vel utilizar gradientes suaves.

Exemplo:

```
from-white/25
to-white/5
```

ou

```
from-sky-400
via-cyan-400
to-indigo-500
```

Evitar gradientes agressivos.

---

## Sombras

As sombras devem simular profundidade.

Preferir:

```
shadow-2xl
shadow-xl
```

ou sombras customizadas.

Nunca utilizar sombras totalmente pretas.

---

## Cantos

Utilizar bordas arredondadas.

Preferencialmente:

```
rounded-3xl

rounded-[28px]

rounded-[32px]
```

Evitar:

```
rounded-sm
```

---

# Reflexo

Pain�is de vidro devem possuir brilho superior.

Adicionar pseudo-elemento:

```
before:absolute
before:inset-0
before:bg-gradient-to-br
before:from-white/25
before:to-transparent
```

Sempre com:

```
pointer-events-none
```

---

# Paleta

## Prim�ria

Azuis claros.

```
Sky
Cyan
Blue
Indigo
```

## Secund�ria

Brancos transl�cidos.

```
white/5

white/10

white/15

white/20

white/30
```

Evitar cinzas escuros como fundo principal.

---

# Tipografia

Utilizar:

```
font-medium

font-semibold
```

Texto principal:

```
text-white
```

Texto secund�rio:

```
text-white/70
```

Texto auxiliar:

```
text-white/50
```

---

# Espa�amentos

Preferir:

```
p-6

p-8

gap-4

gap-6

gap-8
```

Nunca criar componentes "apertados".

---

# �cones

Utilizar:

- Lucide
- Heroicons

Sempre:

```
stroke-1.5
```

Evitar �cones extremamente grossos.

---

# Bot�es

Bot�es devem parecer vidro.

Sempre possuir:

- blur
- borda
- anima��o
- leve brilho

Exemplo:

```
rounded-full

backdrop-blur-xl

border-white/20

hover:bg-white/20

active:scale-95

transition-all
```

---

# Inputs

Inputs devem ser transl�cidos.

Nunca utilizar:

```
bg-white
```

Preferir:

```
bg-white/10

border-white/15

backdrop-blur-xl
```

Placeholder:

```
text-white/40
```

---

# Cards

Todo card deve possuir:

- blur
- sombra
- borda
- brilho
- gradiente

Estrutura:

```
glass

rounded-3xl

border

shadow

backdrop-blur-xl
```

---

# Sidebar

A sidebar deve:

- flutuar sobre o fundo
- possuir transpar�ncia
- n�o utilizar cores s�lidas

---

# Navbar

A navbar deve parecer um painel de vidro.

Sempre utilizar:

```
sticky

backdrop-blur-xl

border-b border-white/10
```

---

# Modais

O modal deve utilizar:

Overlay:

```
bg-black/30

backdrop-blur-sm
```

Painel:

```
glass

rounded-3xl
```

---

# Hover

Todo componente interativo deve possuir anima��o.

Preferir:

```
duration-300

ease-out
```

Hover:

```
translate-y-[-2px]

scale-[1.02]
```

Nunca exagerar.

---

# Focus

Todo input deve possuir:

```
ring-2

ring-sky-400/40
```

---

# Transi��es

Sempre utilizar:

```
transition-all

duration-300
```

Evitar anima��es acima de:

```
400ms
```

---

# Background Global

As p�ginas devem utilizar gradientes.

Exemplo:

```
from-sky-500

via-cyan-400

to-indigo-700
```

ou

```
from-slate-900

via-sky-900

to-indigo-950
```

Adicionar elementos desfocados ao fundo para criar profundidade.

---

# Componentes

Ao criar componentes reutiliz�veis:

Sempre utilizar:

- className
- children
- variantes
- composi��o
- tipagem TypeScript

Evitar componentes gigantes.

---

# Responsividade

Todos os componentes devem ser responsivos.

Utilizar:

```
sm:

md:

lg:

xl:
```

N�o utilizar tamanhos fixos quando n�o forem necess�rios.

---

# Acessibilidade

Todo componente deve:

- possuir foco vis�vel
- contraste suficiente
- aria-label quando necess�rio
- navega��o por teclado

---

# Performance

Evitar:

- anima��es pesadas
- filtros exagerados
- m�ltiplos blurs aninhados

Utilizar blur apenas onde necess�rio.

---

# Resultado Esperado

Toda interface deve transmitir:

- sofistica��o
- fluidez
- leveza
- transpar�ncia
- profundidade
- modernidade

A apar�ncia deve lembrar superf�cies de vidro l�quido iluminadas por luz natural.

Sempre priorizar consist�ncia visual entre todos os componentes da aplica��o.
