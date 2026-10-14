"""Central configuration, read from environment variables (and an optional .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader so the project has no hard dependency on python-dotenv."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    db_path: Path = field(default_factory=lambda: Path(os.getenv("FLEET_DB_PATH", ROOT / "data" / "fleet.db")))
    knowledge_dir: Path = ROOT / "knowledge"
    # anthropic | openai | offline  (offline = retrieval-only demo mode, no API key needed)
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "auto").lower())
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"))
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    max_rows: int = field(default_factory=lambda: int(os.getenv("MAX_ROWS", "500")))
    query_timeout_s: float = field(default_factory=lambda: float(os.getenv("QUERY_TIMEOUT_S", "10")))
    max_repair_attempts: int = field(default_factory=lambda: int(os.getenv("MAX_REPAIR_ATTEMPTS", "2")))
    top_k_examples: int = 4
    top_k_glossary: int = 4

    def resolved_provider(self) -> str:
        if self.llm_provider != "auto":
            return self.llm_provider
        if os.getenv("ANTHROPIC_API_KEY"):
            return "anthropic"
        if os.getenv("OPENAI_API_KEY"):
            return "openai"
        return "offline"


settings = Settings()
