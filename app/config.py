"""Settings read from environment variables (and .env, if present)."""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value else default


def _str(name: str, default: str = "") -> str:
    return os.getenv(name, "").strip() or default


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: _str("DATABASE_URL"))

    groq_api_key: str = field(default_factory=lambda: _str("GROQ_API_KEY"))
    openrouter_api_key: str = field(default_factory=lambda: _str("OPENROUTER_API_KEY"))
    gemini_api_key: str = field(default_factory=lambda: _str("GEMINI_API_KEY"))
    ollama_url: str = field(default_factory=lambda: _str("OLLAMA_URL"))

    groq_model: str = field(default_factory=lambda: _str("GROQ_MODEL", "llama-3.3-70b-versatile"))
    openrouter_model: str = field(
        default_factory=lambda: _str("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    )
    gemini_model: str = field(default_factory=lambda: _str("GEMINI_MODEL", "gemini-2.5-flash"))
    ollama_model: str = field(default_factory=lambda: _str("OLLAMA_MODEL", "qwen2.5:3b"))

    provider_order: list[str] = field(
        default_factory=lambda: [
            p.strip().lower()
            for p in _str("PROVIDER_ORDER", "groq,openrouter,gemini,ollama").split(",")
            if p.strip()
        ]
    )

    max_upload_mb: int = field(default_factory=lambda: _int("MAX_UPLOAD_MB", 10))
    session_ttl_hours: int = field(default_factory=lambda: _int("SESSION_TTL_HOURS", 24))
    rate_limit_per_minute: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_MINUTE", 30))
    llm_timeout_seconds: int = field(default_factory=lambda: _int("LLM_TIMEOUT_SECONDS", 60))

    sentry_dsn: str = field(default_factory=lambda: _str("SENTRY_DSN"))

    # Retrieval / chunking parameters described in the README
    chunk_size: int = 800
    chunk_overlap: int = 120
    top_k: int = 5


settings = Settings()
