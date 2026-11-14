from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_POOL = None
_INITIALIZED = False


def database_url() -> str:
    return (os.getenv("DATABASE_URL") or "").strip()


def using_postgres() -> bool:
    return bool(database_url())


def _pool():
    global _POOL, _INITIALIZED
    if not using_postgres():
        return None
    if _POOL is None:
        import psycopg
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        _POOL = ConnectionPool(
            conninfo=database_url(),
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row},
            open=True,
        )
    if not _INITIALIZED:
        _apply_migrations(_POOL)
        _INITIALIZED = True
    return _POOL


def _apply_migrations(pool) -> None:
    migrations_dir = Path(__file__).resolve().parents[1] / "migrations"
    files = sorted(migrations_dir.glob("*.sql")) if migrations_dir.exists() else []
    with pool.connection() as conn:
        with conn.transaction():
            conn.execute(
                """
                create table if not exists schema_migrations (
                  name text primary key,
                  applied_at timestamptz not null default now()
                )
                """
            )
            done = {
                row["name"]
                for row in conn.execute("select name from schema_migrations").fetchall()
            }
            for path in files:
                if path.name in done:
                    continue
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute(
                    "insert into schema_migrations (name) values (%s)",
                    (path.name,),
                )


def fetch_all(query: str, params: tuple[Any, ...] | list[Any] = ()) -> list[dict[str, Any]]:
    pool = _pool()
    if pool is None:
        return []
    with pool.connection() as conn:
        return list(conn.execute(query, params).fetchall())


def fetch_one(query: str, params: tuple[Any, ...] | list[Any] = ()) -> dict[str, Any] | None:
    pool = _pool()
    if pool is None:
        return None
    with pool.connection() as conn:
        return conn.execute(query, params).fetchone()


def execute(query: str, params: tuple[Any, ...] | list[Any] = ()) -> None:
    pool = _pool()
    if pool is None:
        return
    with pool.connection() as conn:
        with conn.transaction():
            conn.execute(query, params)
