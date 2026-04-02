import json

from taskplane.github_sync import (
    fetch_issues_via_gh,
    persist_issue_import_batch,
)


def test_fetch_issues_via_gh_uses_state_all_and_expected_fields():
    captured = {}

    def fake_runner(command: str) -> str:
        captured["command"] = command
        return json.dumps(
            [
                {
                    "number": 42,
                    "title": "[Story][W0-A] 文档分析与知识蒸馏",
                    "body": "Part of #19.",
                    "state": "OPEN",
                    "url": "https://github.com/codefromkarl/stardrifter/issues/42",
                    "labels": [{"name": "story"}, {"name": "lane:01"}],
                }
            ]
        )

    issues = fetch_issues_via_gh(
        repo="codefromkarl/stardrifter",
        limit=200,
        runner=fake_runner,
    )

    assert issues[0]["number"] == 42
    assert "--state all" in captured["command"]
    assert (
        "--json number,title,body,state,url,labels,createdAt,updatedAt,closedAt"
        in captured["command"]
    )


def test_fetch_issues_via_gh_retries_transient_graphql_eof(monkeypatch):
    calls = {"count": 0}

    def flaky_runner(command: str) -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError('Post "https://api.github.com/graphql": EOF')
        return json.dumps(
            [
                {
                    "number": 107,
                    "title": "[Story][07-D] Hot reload and bridge-facing data access contract",
                    "body": "Part of #62.",
                    "state": "OPEN",
                    "url": "https://github.com/codefromkarl/stardrifter/issues/107",
                    "labels": [{"name": "story"}, {"name": "lane:07"}],
                }
            ]
        )

    monkeypatch.setattr("time.sleep", lambda *_: None)

    issues = fetch_issues_via_gh(
        repo="codefromkarl/stardrifter",
        limit=200,
        runner=flaky_runner,
    )

    assert issues[0]["number"] == 107
    assert calls["count"] == 2


def test_fetch_issues_via_gh_falls_back_to_rest_after_retryable_graphql_failures(
    monkeypatch,
):
    calls = {"commands": []}

    def flaky_runner(command: str) -> str:
        calls["commands"].append(command)
        if "gh issue list" in command:
            raise RuntimeError('Post "https://api.github.com/graphql": EOF')
        return json.dumps(
            [
                {
                    "number": 117,
                    "title": "[07-IMPL] define minimal hot reload contract for data foundation sources",
                    "body": "Part of #107.",
                    "state": "open",
                    "html_url": "https://github.com/codefromkarl/stardrifter/issues/117",
                    "labels": [{"name": "task"}, {"name": "lane:07"}],
                    "created_at": "2026-03-25T00:00:00Z",
                    "updated_at": "2026-03-25T00:00:00Z",
                    "closed_at": None,
                }
            ]
        )

    monkeypatch.setattr("time.sleep", lambda *_: None)

    issues = fetch_issues_via_gh(
        repo="codefromkarl/stardrifter",
        limit=200,
        runner=flaky_runner,
    )

    assert issues[0]["number"] == 117
    assert any("gh issue list" in command for command in calls["commands"])
    assert any(
        "gh api repos/codefromkarl/stardrifter/issues?state=all&per_page=200" in command
        for command in calls["commands"]
    )


def test_persist_issue_import_batch_writes_batch_snapshot_normalized_relations_and_audit():
    connection = FakeConnection()
    raw_issues = [
        {
            "number": 43,
            "title": "[Story][W0-B] GitHub Project 结构初始化",
            "body": "Part of #19.",
            "state": "CLOSED",
            "url": "https://github.com/codefromkarl/stardrifter/issues/43",
            "labels": [{"name": "story"}, {"name": "lane:01"}],
        }
    ]

    persist_issue_import_batch(
        connection=connection,
        repo="codefromkarl/stardrifter",
        raw_issues=raw_issues,
    )

    executed_sql = "\n".join(connection.executed_sql)
    assert "INSERT INTO github_issue_import_batch" in executed_sql
    assert "INSERT INTO github_issue_snapshot" in executed_sql
    assert "INSERT INTO github_issue_normalized" in executed_sql
    assert "INSERT INTO github_issue_relation" in executed_sql
    assert "INSERT INTO github_issue_completion_audit" in executed_sql
    assert connection.commits > 0


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection

    def execute(self, sql: str, params=None) -> None:
        self.connection.executed_sql.append(sql)
        self.connection.executed_params.append(params)

    def fetchone(self):
        if not self.connection.fetchone_results:
            return None
        return self.connection.fetchone_results.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


class FakeConnection:
    def __init__(self) -> None:
        self.executed_sql: list[str] = []
        self.executed_params: list[object] = []
        self.commits = 0
        self.fetchone_results = [
            {"id": 101},
            {"id": 1001},
        ]

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1
