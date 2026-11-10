"""Rotas do método servido e do manifesto de skills. F3.

Cinco rotas, prefixo `/api` (registrado por F1 em `main.py`):

| Rota | Escopo |
| --- | --- |
| `GET /api/method/index` | público |
| `GET /api/method/doc/{doc_id:path}` | público |
| `GET /api/method/search?q=&top=` | público |
| `GET /api/skills/manifest` | autenticado |
| `GET /api/skills/{skill_id}` | autenticado |

`GET /api/method/*` é leitura pública: o site publica o mesmo corpus e ele não
contém segredo. `GET /api/skills/*` exige `require_user` (F1) — as skills de
implementação não são publicadas.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app import db
from app.auth import require_user
from app.config import settings
from app.services.method import MethodIndex, index_chunks, search
from app.services.skills import SkillRegistry

__all__ = ["router", "get_method_service", "get_skill_registry", "reset_services"]

router = APIRouter()

DEFAULT_TOP = 50
MAX_TOP = 200

_lock = asyncio.Lock()
_method_index: MethodIndex | None = None
_skill_registry: SkillRegistry | None = None


# --------------------------------------------------------------------------- #
# Dependências
# --------------------------------------------------------------------------- #


async def get_method_service() -> MethodIndex:
    """Índice do método, com carga preguiçosa e reindexação quando o hash muda."""
    global _method_index
    root = Path(settings.repo_root)
    index = _method_index
    if index is None or index.root != root:
        async with _lock:
            index = _method_index
            if index is None or index.root != root:
                index = MethodIndex(root)
                _method_index = index
                await _sync_chunks(index)
                return index
    if index.refresh():
        await _sync_chunks(index)
    return index


def get_skill_registry() -> SkillRegistry:
    """Registro de skills, com carga preguiçosa."""
    global _skill_registry
    root = Path(settings.repo_root)
    registry = _skill_registry
    if registry is None or registry.root != root:
        registry = SkillRegistry(root)
        _skill_registry = registry
    return registry


def reset_services() -> None:
    """Limpa o cache dos serviços (usado por testes)."""
    global _method_index, _skill_registry
    _method_index = None
    _skill_registry = None


async def _sync_chunks(index: MethodIndex) -> None:
    """Reindexa os chunks no banco. Falha não derruba o boot nem a leitura."""
    try:
        pool = await _pool()
        await index_chunks(pool, index.all())
    except Exception as exc:  # pragma: no cover - banco indisponível
        print(f"[F3] chunks do método não indexados: {exc}", file=sys.stderr)


async def _pool():
    pool = await db.get_pool()
    if pool is None:
        raise RuntimeError("pool do banco indisponível")
    return pool


# --------------------------------------------------------------------------- #
# Erros
# --------------------------------------------------------------------------- #


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    """Envelope único de erro (Contrato Comum §3)."""
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "detail": {}}},
    )


# --------------------------------------------------------------------------- #
# Rotas
# --------------------------------------------------------------------------- #


@router.get("/method/index")
async def method_index(service: MethodIndex = Depends(get_method_service)) -> dict:
    """Categorias e documentos do corpus do método."""
    docs = service.all()
    return {
        "categories": service.categories(),
        "docs": [
            {
                "id": doc.id,
                "title": doc.title,
                "category": doc.category,
                "kind": doc.kind,
                "path": doc.path,
                "hash": doc.hash,
            }
            for doc in docs
        ],
        "corpus_hash": service.corpus_hash,
        "count": len(docs),
    }


@router.get("/method/doc/{doc_id:path}")
async def method_doc(doc_id: str, service: MethodIndex = Depends(get_method_service)):
    """Documento bruto + frontmatter parseado."""
    doc = service.get(doc_id)
    if doc is None:
        return _error(404, "not_found", f"documento não encontrado: {doc_id}")
    return {
        "id": doc.id,
        "title": doc.title,
        "category": doc.category,
        "path": doc.path,
        "frontmatter": doc.frontmatter,
        "content": doc.content,
        "hash": doc.hash,
    }


@router.get("/method/search")
async def method_search(
    q: str = Query(default=""),
    top: int = Query(default=DEFAULT_TOP),
    service: MethodIndex = Depends(get_method_service),
):
    """Busca lexical provisória no corpus do método (FTS puro)."""
    query = q.strip()
    if not query:
        return _error(400, "invalid_query", "q é obrigatório")
    if top < 1 or top > MAX_TOP:
        return _error(400, "invalid_query", f"top deve estar entre 1 e {MAX_TOP}")
    try:
        pool = await _pool()
        hits = await search(pool, query, top)
    except Exception:
        return _error(503, "unavailable", "índice do método indisponível")
    return {"query": query, "hits": hits}


@router.get("/skills/manifest")
async def skills_manifest(
    registry: SkillRegistry = Depends(get_skill_registry),
    user=Depends(require_user),
) -> dict:
    """Manifesto das skills com hash verificável."""
    skills = registry.manifest()
    return {
        "skills": [
            {
                "id": skill.id,
                "version": skill.version,
                "hash": skill.hash,
                "description": skill.description,
                "path": skill.path,
            }
            for skill in skills
        ],
        "corpus_hash": registry.corpus_hash,
        "count": len(skills),
    }


@router.get("/skills/{skill_id}")
async def skill_detail(
    skill_id: str,
    registry: SkillRegistry = Depends(get_skill_registry),
    user=Depends(require_user),
):
    """Conteúdo bruto da skill e seus arquivos auxiliares."""
    skill = registry.get(skill_id)
    if skill is None:
        return _error(404, "not_found", f"skill não encontrada: {skill_id}")
    return {
        "id": skill.id,
        "version": skill.version,
        "hash": skill.hash,
        "description": skill.description,
        "path": skill.path,
        "content": registry.content(skill_id) or "",
        "files": registry.files(skill_id),
    }


async def _startup() -> None:
    """Carga eager do corpus — otimização; a carga tardia é a autoridade."""
    try:
        await get_method_service()
        get_skill_registry()
    except Exception as exc:  # pragma: no cover - nunca derruba o boot
        print(f"[F3] corpus do método não carregado no startup: {exc}", file=sys.stderr)


router.add_event_handler("startup", _startup)
