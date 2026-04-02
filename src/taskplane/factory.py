from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .repository import PostgresControlPlaneRepository


def build_postgres_repository(
    *,
    dsn: str,
    connector: Callable[[str], Any] | None = None,
) -> PostgresControlPlaneRepository:
    if connector is None:
        connector = _default_psycopg_connector
    connection = connector(dsn)
    return PostgresControlPlaneRepository(connection)


def _default_psycopg_connector(dsn: str) -> Any:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError(
            "psycopg is required for PostgreSQL repository usage"
        ) from exc
    return psycopg.connect(dsn, row_factory=dict_row)
