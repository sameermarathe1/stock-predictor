from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path | None = None) -> None:
    """Load a tiny subset of .env syntax without external dependencies."""
    env_path = path or (ROOT_DIR / ".env")
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


@dataclass(slots=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8000
    request_timeout_seconds: int = 18
    suggestions_cache_seconds: int = 900
    openai_api_key: str | None = None
    openai_model: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key and self.openai_model)


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "18")),
        suggestions_cache_seconds=int(os.getenv("SUGGESTIONS_CACHE_SECONDS", "900")),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL"),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
    )
