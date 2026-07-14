from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _secret(name: str, default: str = "") -> str:
    """Read a secret from Docker secrets first, then the environment."""
    file_name = os.getenv(f"{name}_FILE")
    if file_name:
        return Path(file_name).read_text(encoding="utf-8").strip()
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    environment: str
    database_url: str
    public_origin: str
    auth_mode: str
    admin_email: str
    admin_password_hash: str
    cloudflare_team_domain: str
    cloudflare_access_audience: str
    allowed_emails: tuple[str, ...]
    openai_api_key: str
    openai_model: str
    nvidia_api_key: str
    nvidia_base_url: str
    nvidia_model: str
    provider: str
    release_sha: str
    worker_poll_seconds: float
    run_limit_daily: int
    run_limit_active: int

    @property
    def production(self) -> bool:
        return self.environment == "production"

    def validate(self, *, role: str) -> None:
        if self.production and self.auth_mode not in {"cloudflare", "local"}:
            raise RuntimeError("production requires FMC_AUTH_MODE=local or cloudflare")
        if self.auth_mode == "local" and self.production:
            if not self.admin_email or not self.admin_password_hash:
                raise RuntimeError("local production auth requires FMC_ADMIN_EMAIL and password hash")
        if self.auth_mode == "cloudflare":
            if not self.cloudflare_team_domain or not self.cloudflare_access_audience:
                raise RuntimeError("Cloudflare Access team domain and audience are required")
        if role == "worker" and self.provider == "openai" and not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required by the production worker")
        if role == "worker" and self.provider == "nvidia" and not self.nvidia_api_key:
            raise RuntimeError("NVIDIA_API_KEY is required by the production worker")
        if self.production and self.provider not in {"openai", "nvidia"}:
            raise RuntimeError("production requires FMC_PROVIDER=openai or nvidia")
        if self.production and self.database_url.startswith("sqlite"):
            raise RuntimeError("production requires PostgreSQL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    environment = os.getenv("FMC_ENV", "development").strip().lower()
    default_db = "sqlite:///./find-my-customer.db"
    emails = tuple(
        sorted({item.strip().lower() for item in os.getenv("FMC_ALLOWED_EMAILS", "").split(",") if item.strip()})
    )
    settings = Settings(
        environment=environment,
        database_url=_secret("DATABASE_URL", default_db),
        public_origin=os.getenv("FMC_PUBLIC_ORIGIN", "http://127.0.0.1:8000").rstrip("/"),
        auth_mode=os.getenv("FMC_AUTH_MODE", "development").strip().lower(),
        admin_email=os.getenv("FMC_ADMIN_EMAIL", "").strip().lower(),
        admin_password_hash=_secret("FMC_ADMIN_PASSWORD_HASH"),
        cloudflare_team_domain=os.getenv("FMC_CF_TEAM_DOMAIN", "").rstrip("/"),
        cloudflare_access_audience=_secret("FMC_CF_ACCESS_AUDIENCE"),
        allowed_emails=emails,
        openai_api_key=_secret("OPENAI_API_KEY"),
        openai_model=os.getenv("FMC_OPENAI_MODEL", "gpt-5.2").strip(),
        nvidia_api_key=_secret("NVIDIA_API_KEY"),
        nvidia_base_url=os.getenv("FMC_NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/"),
        nvidia_model=os.getenv("FMC_NVIDIA_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1").strip(),
        provider=os.getenv("FMC_PROVIDER", "fixture").strip().lower(),
        release_sha=os.getenv("FMC_RELEASE_SHA", "development").strip(),
        worker_poll_seconds=float(os.getenv("FMC_WORKER_POLL_SECONDS", "2")),
        run_limit_daily=int(os.getenv("FMC_RUN_LIMIT_DAILY", "10")),
        run_limit_active=int(os.getenv("FMC_RUN_LIMIT_ACTIVE", "2")),
    )
    return settings
