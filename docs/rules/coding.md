<!--- Fonte da verdade: toda regra declarativa vive aqui em docs/rules/ --->

# Padrões de desenvolvimento que devem ser respeitas

> Todos os padrões descritos abaixo são obrigatórios

## Logs

- Não logar informações sensíveis, como por exemplo: Número de CPF
- Log de entrada de todos método, exemplo: console.log(`[IN] - Criando aluno`), console.log(`[OUT] - Criando aluno no banco de dados`), console.log(`[IN] - Aluno criado $`{alunoId}`);
