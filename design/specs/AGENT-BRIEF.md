# Brief do Implementador SDD

Você implementa **UMA fase** (F1..F10) do ambiente SDD multi-agentes do Blueprint.
Você está no worktree git da sua fase. Sua branch é a da sua fase. Não toque na branch
de integração.

## Leia nesta ordem, antes de escrever qualquer código

1. `design/specs/2026-11-10-contrato-comum.md` — **CONTRATO VINCULANTE**.
   Convenções de API, banco, env, auth, contratos de módulo, **matriz de ownership**
   (§8) e correções ao design master (§8.2). Em conflito com qualquer outra fonte,
   o contrato prevalece.
2. `design/specs/2026-11-10-fase-F<N>-<sua-fase>.md` — **sua spec**.
   Escopo, contratos, tarefas, critérios de aceitação, testes.
3. `design/specs/2026-11-10-ambiente-sdd-multi-agentes-design.md` — design master.
   Referência. Use para o que a sua spec não detalhar.

O arquivo de dúvidas da fase (`duvidas-*.md`) é onde você registra o que ficou em
dúvida — em vez de inventar.

## Regras duras

- **Toque apenas nos arquivos que sua spec lista como seus** (contrato §8). Nunca
  edite arquivo de outra fase, nunca edite `tools/`, nunca edite `docs/`, nunca
  edite `design/specs/`.
- **Nunca** `git push`, nunca `git checkout` de outra branch, nunca commit na branch
  de integração. Commit só na sua branch, no seu worktree, com mensagem descritiva
 REFIXADA COM `F<n>:`.
- **Sem placeholders**: nada de `TODO`, `FIXME`, `pass  #`, stub vazio sem docstring
  com o número da fase. Se uma parte estiver fora do seu escopo, documente por quê.
- **Sem inventar API**: os endpoints são os do design master §17 + correções do
  contrato §8.2. Nenhuma tabela nova além do DDL do master §8 — coluna extra é
  "adiciona coluna", nunca reescreve tabela.
- **Python do servidor**: async, tipado, stdlib-first. Não adicione dependência que
  a stdlib resolve. PyYAML é aceitável (frontmatter YAML).
- **Testes**: escreva os que sua spec pede e **roda**. Traga o output real. Nunca
  afirme que um teste passou sem ter visto passar.
- **Dependência de fase não pronta**: implemente contra o contrato e marque o teste
  dependente com `@pytest.mark.skip(reason="F<n> pendente")`. Não bloqueie, não invente.
- Erro de auth/estado nunca pode deixar estado parcial.

## Ao terminar

Rode a suíte da sua fase e **deixe o output real no relatório**. Depois chame, no seu
terminal:

```
maestri ask "maestro" "<relatorio: arquivos criados | arquivos editados | output real dos testes | decisoes que o contrato nao cobriu | duvidas>"
```

O relatório precisa conter o output real dos testes, não um resumo.
