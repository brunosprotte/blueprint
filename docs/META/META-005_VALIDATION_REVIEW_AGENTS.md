# META-005 — Validation Review Agents

## Objetivo

Registrar o fluxo obrigatório de validação final após qualquer BR ou SPEC gerada.

## Regra

Ao terminar a escrita de uma BR ou SPEC e após a aprovação do usuário, executar sempre nesta ordem:

1. Blind Hunter
2. Edge Case Hunter
3. Acceptance Auditor

## Resultado esperado

- Cada agente produz análise própria.
- Achados ficam registrados no arquivo de dúvidas do próprio artefato.
- Só concluir a entrega depois de tratar achados reais ou classificá-los como deferidos.
- Se houver dúvidas abertas, o artefato permanece em `on agents review`.
- O catálogo central é atualizado apenas para localização rápida de pendências abertas.
- Quando todas as dúvidas forem `cleaned`, o agente solicita confirmação para avançar o status para `approved`.

## Convenção de arquivos

- Blind Hunter: `docs/implementation-artifacts/review-<tema>-blind-hunter.md`
- Edge Case Hunter: `docs/implementation-artifacts/review-<tema>-edge-case-hunter.md`
- Acceptance Auditor: `docs/implementation-artifacts/review-<tema>-acceptance-auditor.md`
- BR doubts files: `docs/implementation-artifacts/duvidas-br/<BR-id>.md`
- SPEC doubts files: `docs/implementation-artifacts/duvidas-spec/<SPEC-id>.md`
- BR pending catalog: `docs/implementation-artifacts/duvidas-br.md`
- SPEC pending catalog: `docs/implementation-artifacts/duvidas-spec.md`

## Aplicação

- Esta regra vale para toda BR nova, toda SPEC nova e toda alteração relevante.
- O rastreio de dúvidas deve seguir META-006.
- Se o projeto não tiver registro local dos agentes, este documento é a fonte canônica.
