"""Registro de skills de implementação — `skills/` do repo blueprint. F3.

Layout servido: `skills/<id>/SKILL.md` — mesma forma do que o Claude Code consome
em `.claude/skills/<id>/SKILL.md` (por isso o kit copia 1:1).

O diretório `skills/` é **conteúdo de repo**, não código: F3 não o cria. A ausência
é tolerada — o servidor sobe com ou sem `skills/`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.method import sha256_hex, split_frontmatter

__all__ = ["Skill", "SkillRegistry", "SKILL_FILE"]

#: Nome do arquivo principal de uma skill.
SKILL_FILE = "SKILL.md"


@dataclass(frozen=True)
class Skill:
    """Uma skill de implementação."""

    id: str
    version: str
    hash: str
    description: str
    path: str


class SkillRegistry:
    """Índice das skills de implementação em `root/skills`."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.skills_dir = self.root / "skills"
        self._skills: dict[str, Skill] = {}
        self._contents: dict[str, str] = {}
        self._files: dict[str, dict[str, str]] = {}
        self._corpus_hash = ""
        self.refresh()

    # -- leitura ------------------------------------------------------------ #

    @property
    def corpus_hash(self) -> str:
        return self._corpus_hash

    def manifest(self) -> list[Skill]:
        """Todas as skills, ordenadas por id."""
        return [self._skills[key] for key in sorted(self._skills)]

    def get(self, skill_id: str) -> Skill | None:
        if not skill_id:
            return None
        return self._skills.get(skill_id.strip())

    def content(self, skill_id: str) -> str | None:
        """Conteúdo bruto do `SKILL.md`."""
        if not skill_id:
            return None
        return self._contents.get(skill_id.strip())

    def files(self, skill_id: str) -> dict[str, str]:
        """Arquivos auxiliares da skill (tudo menos o `SKILL.md`)."""
        if not skill_id:
            return {}
        return dict(self._files.get(skill_id.strip(), {}))

    # -- manutenção --------------------------------------------------------- #

    def refresh(self) -> bool:
        """Recalcula o registro. Devolve `True` se o conjunto de skills mudou."""
        skills: dict[str, Skill] = {}
        contents: dict[str, str] = {}
        files: dict[str, dict[str, str]] = {}
        corpus_parts: list[str] = []

        for directory in self._iter_skill_dirs():
            main = directory / SKILL_FILE
            if not main.is_file():
                continue
            raw = main.read_bytes()
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:  # pragma: no cover - skills são UTF-8
                content = raw.decode("utf-8", errors="replace")
            frontmatter, _ = split_frontmatter(content)

            skill_id = frontmatter.get("name", "").strip() or directory.name
            version = frontmatter.get("version", "").strip() or "0.0.0"
            description = frontmatter.get("description", "").strip()

            skill_files: dict[str, str] = {}
            skill_parts: list[str] = []
            entries: list[tuple[str, Path]] = []
            for path in directory.rglob("*"):
                if path.is_file():
                    entries.append((path.relative_to(directory).as_posix(), path))
            entries.sort(key=lambda item: item[0])
            for rel, path in entries:
                payload = path.read_bytes()
                skill_parts.append(f"{rel}\0{sha256_hex(payload)}\n")
                corpus_parts.append(f"{directory.name}/{rel}\0{sha256_hex(payload)}\n")
                if rel != SKILL_FILE:
                    try:
                        skill_files[rel] = payload.decode("utf-8")
                    except UnicodeDecodeError:  # pragma: no cover
                        skill_files[rel] = payload.decode("utf-8", errors="replace")

            skills[skill_id] = Skill(
                id=skill_id,
                version=version,
                hash=sha256_hex("".join(skill_parts)),
                description=description,
                path=f"skills/{directory.name}/{SKILL_FILE}",
            )
            contents[skill_id] = content
            files[skill_id] = skill_files

        corpus_hash = sha256_hex("".join(sorted(corpus_parts)))
        changed = corpus_hash != self._corpus_hash
        self._skills = skills
        self._contents = contents
        self._files = files
        self._corpus_hash = corpus_hash
        return changed

    # -- interno ------------------------------------------------------------ #

    def _iter_skill_dirs(self) -> list[Path]:
        if not self.skills_dir.is_dir():
            return []
        dirs = [
            path
            for path in sorted(self.skills_dir.iterdir())
            if path.is_dir() and not path.name.startswith(".")
        ]
        return dirs
