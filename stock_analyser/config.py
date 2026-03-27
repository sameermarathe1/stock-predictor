from __future__ import annotations

import os
import random
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


def split_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


@dataclass(slots=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8000
    request_timeout_seconds: int = 18
    suggestions_cache_seconds: int = 900
    openai_api_key: str | None = None
    openai_model: str | None = None
    openai_counsel_models: tuple[str, ...] = ()
    openai_counsel_max_members: int = 5
    openai_counsel_timeout_seconds: int = 90
    openai_base_url: str = "https://api.openai.com/v1"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key and self.openai_model)

    @property
    def counsel_models(self) -> tuple[str, ...]:
        if self.openai_counsel_models:
            return self.openai_counsel_models
        if self.openai_model:
            return (self.openai_model,)
        return ()

    @property
    def counsel_enabled(self) -> bool:
        return bool(self.openai_api_key and self.counsel_models)

    def counsel_member_limit(self) -> int:
        return max(2, min(self.openai_counsel_max_members, 5))

    def counsel_timeout_seconds(self) -> int:
        return max(self.request_timeout_seconds, self.openai_counsel_timeout_seconds)

    def pick_counsel_models(self, member_count: int) -> list[str]:
        pool = self.counsel_models
        if not pool:
            return []
        if member_count <= len(pool):
            return random.sample(list(pool), k=member_count)

        selected = random.sample(list(pool), k=len(pool))
        while len(selected) < member_count:
            selected.append(random.choice(pool))
        return selected


def load_settings() -> Settings:
    load_dotenv()
    openai_model = os.getenv("OPENAI_MODEL")
    counsel_models = split_csv(os.getenv("OPENAI_COUNSEL_MODELS")) or (
        (openai_model,) if openai_model else ()
    )
    return Settings(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "18")),
        suggestions_cache_seconds=int(os.getenv("SUGGESTIONS_CACHE_SECONDS", "900")),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=openai_model,
        openai_counsel_models=counsel_models,
        openai_counsel_max_members=int(os.getenv("OPENAI_COUNSEL_MAX_MEMBERS", "5")),
        openai_counsel_timeout_seconds=int(
            os.getenv("OPENAI_COUNSEL_TIMEOUT_SECONDS", "90")
        ),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
    )
