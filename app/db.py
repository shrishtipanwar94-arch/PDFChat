"""psycopg connection pool, with pgvector types registered on every connection."""

from pathlib import Path

from pgvector.psycopg import register_vector
from psycopg import Connection
from psycopg_pool import ConnectionPool

from app.config import settings

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"

pool: ConnectionPool | None = None


def _configure(conn: Connection) -> None:
    register_vector(conn)


def apply_schema() -> None:
    """Run db/schema.sql (idempotent), so a fresh database works without psql."""
    import psycopg

    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))


def open_pool() -> None:
    global pool
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not set")
    apply_schema()
    pool = ConnectionPool(
        settings.database_url,
        min_size=1,
        max_size=10,
        configure=_configure,
        open=True,
    )


def close_pool() -> None:
    global pool
    if pool is not None:
        pool.close()
        pool = None


def get_pool() -> ConnectionPool:
    if pool is None:
        raise RuntimeError("Database pool is not open")
    return pool
