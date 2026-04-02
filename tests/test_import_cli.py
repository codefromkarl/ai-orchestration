from taskplane.import_cli import main


def test_import_cli_fetches_and_persists(monkeypatch, capsys):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured = {}

    def fake_repository_builder(*, dsn: str):
        captured["dsn"] = dsn
        return {"connection": "ok"}

    def fake_fetcher(*, repo: str, limit: int):
        captured["repo"] = repo
        captured["limit"] = limit
        return [
            {
                "number": 42,
                "title": "[Story][W0-A] 文档分析与知识蒸馏",
                "body": "Part of #19.",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/42",
                "labels": [{"name": "story"}, {"name": "lane:01"}],
            }
        ]

    def fake_persister(*, connection, repo: str, raw_issues):
        captured["connection"] = connection
        captured["persist_repo"] = repo
        captured["issue_count"] = len(raw_issues)

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter", "--limit", "200"],
        repository_builder=fake_repository_builder,
        fetcher=fake_fetcher,
        persister=fake_persister,
    )

    assert exit_code == 0
    assert captured["dsn"] == "postgresql://user:pass@localhost:5432/stardrifter"
    assert captured["repo"] == "codefromkarl/stardrifter"
    assert captured["persist_repo"] == "codefromkarl/stardrifter"
    assert captured["issue_count"] == 1
    assert "imported 1 issues" in capsys.readouterr().out
