"""Configuração do servidor — variáveis de ambiente `SDD_*` (Contrato Comum §5)."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Ajustes do servidor lidos do ambiente.

    Módulo read-only: nenhum service escreve env. Testes usam
    `monkeypatch.setenv` antes de importar `app.config`.
    """

    model_config = SettingsConfigDict(
        env_prefix="SDD_", env_file=".env", extra="ignore"
    )

    database_url: str = "postgresql://sdd:sdd@localhost:5432/sdd"
    secret_key: str
    repo_root: Path = Path(__file__).resolve().parents[2]
    base_url: str = "http://localhost:8000"
    github_client_id: str | None = None
    github_client_secret: str | None = None
    allow_dev_auth: bool = False
    llm_model: str = "claude-opus-5-5"


settings = Settings()
