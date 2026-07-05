# TS-002 � Prisma Persistence Standard

> **Technology Standard**

| Campo          | Valor                                |
| -------------- | ------------------------------------ |
| **ID**         | TS-002                               |
| **T�tulo**     | Prisma Persistence Standard          |
| **Vers�o**     | 1.0.0                                |
| **Status**     | Approved                             |
| **Tecnologia** | Prisma ORM                           |
| **Aplica-se**  | Projetos Blueprint utilizando Prisma |

---

# 1. Technology Question

Como implementar capacidades de persist�ncia utilizando Prisma sem violar a arquitetura do Blueprint?

---

# 2. Purpose

Este documento define como Prisma deve ser utilizado.

Prisma implementa persist�ncia.

Prisma nunca define arquitetura.

Toda comunica��o com Prisma ocorre atrav�s de Output Adapters.

---

# 3. Technology Mapping

| Blueprint      | Prisma        |
| -------------- | ------------- |
| Output Port    | Interface     |
| Output Adapter | Classe        |
| Persist�ncia   | Prisma Client |
| Domain         | Independente  |
| Contract       | N�o utilizado |
| Mapper         | Adapter       |

---

# 4. Directory Structure

```text
infrastructure/

+-- persistence/

    +-- prisma.ts

    +-- schema.prisma

    +-- migrations/

    +-- repositories/

        +-- aluno.repository.ts

        +-- turma.repository.ts

        +-- presenca.repository.ts
```

---

# 5. Dependency Flow

```text
Use Case

?

Output Port

?

Persistence Adapter

?

Prisma Client

?

Database
```

Nunca inverter esse fluxo.

---

# 6. Adapter Rules

Todo Output Adapter:

- implementa exatamente um Output Port;
- depende do Prisma Client;
- converte registros em Domain;
- converte Domain em registros.

Nunca retorna modelos do Prisma.

---

# 7. Repository Example

```ts
export class PrismaAlunoRepository implements AlunoRepositoryPort {
  constructor(private readonly prisma: PrismaClient) {}

  async findByCpf(cpf: string): Promise<Aluno | null> {
    const record = await this.prisma.aluno.findUnique({
      where: { cpf },
    });

    if (!record) {
      return null;
    }

    return AlunoMapper.toDomain(record);
  }

  async save(aluno: Aluno): Promise<Aluno> {
    const created = await this.prisma.aluno.create({
      data: AlunoMapper.toPersistence(aluno),
    });

    return AlunoMapper.toDomain(created);
  }
}
```

---

# 8. Mapper Rules

Toda tradu��o ocorre dentro do Adapter.

Recomendado:

```text
AlunoMapper

?

toDomain()

?

toPersistence()
```

Nunca utilizar objetos do Prisma dentro do Domain.

---

# 9. Prisma Client

Existe apenas uma inst�ncia.

```ts
import { PrismaClient } from "@prisma/client";

export const prisma = new PrismaClient();
```

Nunca criar m�ltiplas inst�ncias.

---

# 10. Domain Isolation

� proibido:

```ts
import { PrismaClient }
```

dentro de:

- Domain
- Use Cases
- Contracts
- Ports

---

# 11. Transaction Rules

Transa��es pertencem ao Adapter.

Nunca ao Use Case.

Exemplo:

```ts
await prisma.$transaction(async (tx) => {});
```

---

# 12. Error Translation

Erros do Prisma nunca atravessam a arquitetura.

Sempre traduzir.

```text
Prisma Error

?

Infrastructure Failure

?

Application Failure
```

---

# 13. Generated Types

� proibido utilizar tipos gerados pelo Prisma fora dos Adapters.

---

# 14. AI Checklist

Antes de gerar c�digo verificar:

- [ ] Existe Output Port?
- [ ] Existe Adapter?
- [ ] Adapter implementa Port?
- [ ] Existe Mapper?
- [ ] Domain permanece puro?
- [ ] Use Case desconhece Prisma?
- [ ] Apenas Adapter importa Prisma?
- [ ] Apenas Adapter traduz registros?

---

# 15. AI Interpretation

Ao implementar persist�ncia utilizando Prisma o agente deve concluir que:

- Prisma pertence exclusivamente aos Output Adapters.
- O Domain nunca conhece o Prisma.
- O Use Case nunca conhece o Prisma.
- Toda tradu��o ocorre no Adapter.
- Toda persist�ncia ocorre atrav�s de Output Ports.

---

# 16. References

Este documento implementa:

- ES-007 � Output Port Model
- ES-009 � Adapter Model
- LS-001 � TypeScript Representation Standard

Complementa:

- TS-001 � Next.js Standard
