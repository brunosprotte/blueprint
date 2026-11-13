---
id: SPEC-001
module: login
feature: login
type: Functional Specification
title: API de autenticação
description: Especificação funcional do endpoint de autenticação por e-mail e senha.
createdBy: SK-002
createdFrom: BR-001
technologyPack: TP-001
status: draft
tags: [login, api]
timestamp: "2026-11-10T00:00:00Z"
doubtsIndex: docs/implementation-artifacts/duvidas-spec/SPEC-001.md
version: 1.0.0
---

# SPEC-001 — API de autenticação

## Objetivo

Autenticar um usuário no sistema a partir de e-mail e senha e devolver um
token de sessão.

## Escopo

Somente a autenticação. Recuperação de senha e cadastro de usuário não fazem
parte desta SPEC.

## Responsabilidade

Uma única responsabilidade: validar credenciais e emitir token de sessão.

## Entradas

- `email`: string obrigatória, formato de e-mail.
- `password`: string obrigatória, entre 8 e 16 caracteres.

## Saídas

- `token`: string opaca de sessão, ou erro de validação.

## Fluxo principal

1. O cliente envia e-mail e senha.
2. A API busca o usuário pelo e-mail.
3. A API compara a senha com o hash armazenado.
4. A API emite o token de sessão e devolve `200`.

## Fluxos alternativos

- Credenciais inválidas devolvem `401` com a mesma mensagem nos dois casos.

## Validações

- E-mail ausente ou malformado: `400`.
- Senha fora do intervalo de tamanho: `400`.

## Failures

- Falha de banco na busca do usuário: `500` sem detalhe técnico.

## Pré-condições

- O usuário está cadastrado no sistema.
- A convenção de workspace [[META-004]] está aplicada.

## Pós-condições

- Existe uma sessão ativa para o usuário autenticado.

## Acceptance Criteria atendidos

- **AC-001** — A autenticação com credenciais válidas devolve token de sessão.
- **AC-002** — A autenticação com credenciais inválidas devolve `401` sem
  revelar qual credencial falhou.

## Dependências

Nenhuma dependência técnica.

## Blueprint Documents necessários

- META-000 — Blueprint Knowledge Model
- META-004 — Workspace Convention
