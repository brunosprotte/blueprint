---
id: BR-001
module: login
feature: login
type: Business Rule
title: Autenticação de usuário
description: Regras de negócio para autenticação de usuário com e-mail e senha.
status: draft
tags: [login, autenticacao]
timestamp: "2026-11-10T00:00:00Z"
doubtsIndex: docs/implementation-artifacts/duvidas-br/BR-001.md
version: 1.0.0
generatedBy: SK-001
---

# BR-001 — Autenticação de usuário

## Objetivo

Permitir que um usuário cadastrado entre no sistema com e-mail e senha.

## Contexto

O sistema hoje não possui autenticação própria; cada aplicação implementa
o seu próprio login.

## Atores

- Usuário cadastrado
- Administrador

## Capacidades

- Autenticar-se no sistema
- Encerrar a sessão ativa

## Regras de Negócio

- O e-mail é obrigatório e único por usuário.
- A senha tem no máximo 16 caracteres.
- A mensagem de erro não revela se o e-mail existe.

## Restrições

- Nenhuma informação técnica no documento.

## Exceções

- Usuário bloqueado após cinco tentativas malsucedidas.

## Acceptance Criteria

- **AC-001** — Quando o usuário informa e-mail e senha válidos, o sistema deve
  autenticar e redirecionar para a página inicial.
- **AC-002** — Quando a senha é inválida, o sistema deve exibir "Usuário ou senha
  inválidos" sem identificar qual dos dois está incorreto.

## Open Questions

- A redefinição de senha entra nesta BR ou em uma BR separada?
