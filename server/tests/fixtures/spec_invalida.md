---
id: SPEC-900
module: checkout
feature: checkout
type: Functional Specification
title: SPEC de checkout inválida
description: SPEC usada nos testes como exemplo de artefato fora do padrão.
createdBy: SK-002
createdFrom: BR-999
status: publicado
tags: [checkout]
timestamp: "2026-11-10T00:00:00Z"
doubtsIndex: docs/duvidas/SPEC-900.md
version: 1.0.0
---

# SPEC-900 — SPEC de checkout inválida

## Objetivo

Documento de exemplo com violações propositais.

## Escopo

Somente o checkout.

## Responsabilidade

Uma responsabilidade técnica.

## Entradas

- `items`: lista de itens.

## Saídas

- `order`: pedido criado.

## Fluxo principal

1. O cliente envia os itens.
2. O backend cria o pedido.

## Fluxos alternativos

- Estoque insuficiente devolve erro.

## Pré-condições

- O usuário está autenticado.

## Pós-condições

- O pedido existe.

## Acceptance Criteria atendidos

- **AC-777** — Critério que não existe na BR de origem.

## Dependências

Nenhuma.

## Blueprint Documents necessários

- META-999 — Blueprint inexistente
