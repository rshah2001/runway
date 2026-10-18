"""Shared Tiger Data (Postgres + TimescaleDB) connection pool, opened on first use."""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import get_settings

_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            get_settings().database_url,
            # several open screens each load 3-6 endpoints at once, plus the background safety-net pass:
            # 5 connections ran out (PoolTimeout) and requests then waited 30 s and failed
            min_size=2,
            max_size=15,
            timeout=8,  # if it's ever exhausted again, fail fast instead of hanging a screen for 30 s
            kwargs={"row_factory": dict_row, "connect_timeout": 10},
            open=True,
        )
    return _pool


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    """A pooled connection; commits on success, rolls back on error."""
    with _get_pool().connection() as conn:
        yield conn


def close() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
