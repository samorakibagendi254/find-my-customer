from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import Base


@lru_cache(maxsize=1)
def engine():
    settings = get_settings()
    kwargs = {"pool_pre_ping": True}
    if settings.database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(settings.database_url, **kwargs)


@lru_cache(maxsize=1)
def session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=engine(), expire_on_commit=False)


def migrate() -> None:
    """Apply the additive v1 schema. Future changes use explicit numbered migrations."""
    Base.metadata.create_all(engine())
    with engine().begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO schema_versions(version) VALUES (1) ON CONFLICT DO NOTHING"))


if __name__ == "__main__":
    migrate()
