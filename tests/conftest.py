from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, cast

import pytest

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(scope="session")
def postgres_test_dsn() -> str:
    dsn = os.getenv("STARDRIFTER_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("STARDRIFTER_TEST_POSTGRES_DSN is not set")
    if psycopg is None or dict_row is None:
        pytest.skip("psycopg is not installed")
    return dsn


@pytest.fixture(scope="session")
def postgres_schema_ready(postgres_test_dsn: str) -> str:
    schema_sql = (ROOT / "sql" / "control_plane_schema.sql").read_text(encoding="utf-8")
    assert psycopg is not None
    with psycopg.connect(postgres_test_dsn, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(cast(Any, schema_sql))
    return postgres_test_dsn


@pytest.fixture
def postgres_test_db(postgres_schema_ready: str) -> str:
    assert psycopg is not None
    with psycopg.connect(postgres_schema_ready, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                TRUNCATE TABLE
                    verification_evidence,
                    execution_run,
                    pull_request_link,
                    work_claim,
                    work_target,
                    work_dependency,
                    story_dependency,
                    work_item
                RESTART IDENTITY CASCADE
                """
            )
    return postgres_schema_ready
