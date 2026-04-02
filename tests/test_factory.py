from taskplane.factory import build_postgres_repository
from taskplane.repository import PostgresControlPlaneRepository


def test_build_postgres_repository_uses_injected_connector():
    captured = {}

    def fake_connector(dsn: str):
        captured["dsn"] = dsn
        return {"dsn": dsn}

    repository = build_postgres_repository(
        dsn="postgresql://user:pass@localhost:5432/stardrifter",
        connector=fake_connector,
    )

    assert isinstance(repository, PostgresControlPlaneRepository)
    assert captured["dsn"] == "postgresql://user:pass@localhost:5432/stardrifter"
