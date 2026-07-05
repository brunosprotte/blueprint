# PAT-001 — Stable UI Identifier

> **Pattern**

| Campo           | Valor                 |
| --------------- | --------------------- |
| **ID**          | PAT-001               |
| **Título**      | Stable UI Identifier  |
| **Versão**      | 1.0.0                 |
| **Status**      | Approved              |
| **Owner**       | Blueprint Engineering |
| **Obrigatório** | Sim (Front-end)       |
| **Aplica-se**   | Interfaces de Usuário |

---

# 1. Pattern Question

Como identificar elementos da interface de forma estável, independente da tecnologia utilizada e resistente a mudanças visuais?

---

# 2. Purpose

Este Pattern define um mecanismo padronizado para identificação de elementos da interface.

Seu objetivo é permitir que ferramentas automatizadas identifiquem componentes de forma consistente durante todo o ciclo de vida da aplicação.

Os identificadores definidos por este Pattern são independentes de:

- layout;
- texto apresentado ao usuário;
- idioma;
- CSS;
- framework;
- biblioteca de componentes.

---

# 3. Motivation

Elementos da interface mudam constantemente.

Podem mudar:

- textos;
- ícones;
- estilos;
- posicionamento;
- componentes visuais.

Essas mudanças não devem invalidar automações nem testes.

Um identificador estável preserva a identidade funcional do elemento.

---

# 4. Responsibilities

O Stable UI Identifier possui apenas uma responsabilidade.

Identificar unicamente um elemento funcional da interface.

Ele não representa:

- aparência;
- estilo;
- comportamento;
- acessibilidade;
- lógica de negócio.

---

# 5. Naming Strategy

O identificador deve representar:

```text
<feature>-<elemento>
```

Exemplos.

```text
login-email

login-password

login-submit

aluno-nome

aluno-cpf

aluno-save

turma-nome

turma-save

presenca-data

presenca-confirm
```

O nome deve permanecer estável durante toda a vida da funcionalidade.

---

# 6. Stability Rules

O identificador nunca deve depender de:

- texto exibido;
- idioma;
- classe CSS;
- posição na tela;
- estrutura do DOM;
- biblioteca utilizada.

Mudanças visuais nunca alteram o identificador.

---

# 7. Lifecycle

O ciclo de vida de um identificador acompanha a funcionalidade.

```text
Feature criada
        │
        ▼
Identificador criado
        │
        ▼
Elemento evolui
        │
        ▼
Identificador permanece
        │
        ▼
Feature removida
        │
        ▼
Identificador removido
```

---

# 8. Uniqueness

Cada elemento funcional deve possuir um identificador único dentro da Feature.

Exemplo.

```text
login-email

login-password

login-submit
```

Não utilizar:

```text
input

button

save

field
```

---

# 9. Technology Independence

Este Pattern não define como o identificador será representado.

A representação pertence aos Technology Standards.

Exemplos possíveis.

- atributo HTML;
- propriedade de componente;
- metadata;
- atributo customizado.

---

# 10. Recommended Usage

Utilizar Stable UI Identifier para:

- formulários;
- botões;
- campos;
- tabelas;
- ações;
- diálogos;
- filtros;
- menus;
- componentes interativos.

Não é necessário para elementos puramente decorativos.

---

# 11. Consumers

Os identificadores podem ser utilizados por:

- testes unitários;
- testes E2E;
- automação;
- ferramentas de acessibilidade;
- ferramentas de inspeção;
- agentes de IA;
- scripts de validação;
- ferramentas futuras.

O Pattern não depende de um consumidor específico.

---

# 12. Architectural Benefits

A utilização deste Pattern proporciona:

- estabilidade;
- desacoplamento;
- rastreabilidade;
- reutilização;
- automação previsível.

---

# 13. Forbidden

É proibido identificar elementos utilizando:

- texto da interface;
- classes CSS;
- posição no DOM;
- índices;
- ordem de renderização;
- seletores frágeis.

---

# 14. AI Interpretation

Ao interpretar este Pattern, um agente deve concluir que:

- toda Feature possui elementos identificáveis;
- identificadores representam intenção funcional;
- identificadores permanecem estáveis durante a evolução da interface;
- tecnologias diferentes podem representar o mesmo identificador de maneiras diferentes.

---

# 15. References

Este Pattern pode ser implementado por diferentes tecnologias de interface.

Exemplos incluem:

- atributos HTML específicos;
- propriedades de componentes;
- mecanismos equivalentes definidos pelos Technology Standards.

A forma concreta de implementação pertence aos respectivos Technology Standards.
