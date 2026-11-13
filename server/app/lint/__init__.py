"""Linter de artefatos do Blueprint — fase F2.

API pública (contrato comum §7.2).
"""

from .rules import Finding, Rule, RULES
from .runner import (
    ArtifactDoc,
    CompositeUniverse,
    LinkUniverse,
    MethodCorpus,
    SyncedArtifacts,
    lint_batch,
    lint_document,
    parse_document,
)

__all__ = [
    "Finding",
    "Rule",
    "RULES",
    "ArtifactDoc",
    "LinkUniverse",
    "MethodCorpus",
    "SyncedArtifacts",
    "CompositeUniverse",
    "lint_document",
    "lint_batch",
    "parse_document",
]
