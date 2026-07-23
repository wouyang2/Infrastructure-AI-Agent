from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from storage.models import Base


DEFAULT_DATABASE_URL = "sqlite:///artifacts/infra_agent.db"


def database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def build_engine(url: str | None = None):
    url = url or database_url()
    if url.startswith("sqlite:///"):
        database_path = Path(url.removeprefix("sqlite:///"))
        if database_path.parent != Path("."):
            database_path.parent.mkdir(parents=True, exist_ok=True)
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
        )
    return create_engine(url)


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_database() -> None:
    Base.metadata.create_all(bind=engine)
    _apply_lightweight_sqlite_migrations()


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _apply_lightweight_sqlite_migrations() -> None:
    if not database_url().startswith("sqlite:///"):
        return

    inspector = inspect(engine)
    if "inspection_runs" not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("inspection_runs")
    }
    statements = {
        "review_status": (
            "ALTER TABLE inspection_runs "
            "ADD COLUMN review_status VARCHAR(32) DEFAULT 'not_reviewed'"
        ),
        "reviewer_notes": "ALTER TABLE inspection_runs ADD COLUMN reviewer_notes TEXT",
        "reviewed_by": "ALTER TABLE inspection_runs ADD COLUMN reviewed_by VARCHAR(128)",
        "reviewed_at": "ALTER TABLE inspection_runs ADD COLUMN reviewed_at DATETIME",
    }
    with engine.begin() as connection:
        for column_name, statement in statements.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))
