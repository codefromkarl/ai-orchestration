from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class PostgresSettings:
    dsn: str


def load_postgres_settings_from_env() -> PostgresSettings:
    dsn = os.getenv("TASKPLANE_DSN", "").strip()
    if not dsn:
        raise RuntimeError("TASKPLANE_DSN is required")
    return PostgresSettings(dsn=dsn)
