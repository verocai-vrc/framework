"""Application settings, loaded from environment variables and an optional ``.env`` file.

``PASSIVE_ONLY`` is the global guard from the brief (Section 2.1): when true, any collector
that declares ``interacts_with_target = True`` is refused before it runs.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root: backend/app/config.py -> backend/app -> backend -> repo
REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "frontend"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Working project name; the user will pick a final name later, so keep it in one place.
    app_name: str = "OSINTree"

    # --- Non-negotiable guard (brief, Section 2.1) ---
    passive_only: bool = Field(default=True, description="Refuse collectors that touch the target")

    # --- Neo4j ---
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "osintree-dev"
    neo4j_database: str = "neo4j"
    neo4j_connect_timeout: float = 5.0

    # --- HTTP server ---
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"

    # --- Collectors ---
    cache_dir: Path = REPO_ROOT / ".cache"
    http_timeout: float = 20.0
    http_user_agent: str = "OSINTree/0.1 (+passive OSINT research tool)"

    # --- UI / report localisation ---
    default_locale: str = "en"
    report_locale: str = "pt"


@lru_cache
def get_settings() -> Settings:
    return Settings()
