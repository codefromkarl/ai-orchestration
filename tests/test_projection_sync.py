from typing import cast

from taskplane.models import (
    GitHubTaskProjection,
    WorkDependency,
    WorkItem,
)
from taskplane.projection_sync import (
    sync_projection_to_control_plane,
)


def test_sync_projection_to_control_plane_writes_work_items_and_dependencies():
    projection = GitHubTaskProjection(
        work_items=[
            WorkItem(
                id="issue-56",
                title="[03-DOC] 为 03-C 三条开放项补充 wave 标记与后续 task 跟踪",
                lane="Lane 03",
                wave="unassigned",
                status="done",
                complexity="low",
                source_issue_number=56,
                canonical_story_issue_number=29,
            ),
            WorkItem(
                id="issue-57",
                title="[03-DOC] 在 DoD 下补充整体完成判定声明",
                lane="Lane 03",
                wave="unassigned",
                status="pending",
                complexity="low",
                source_issue_number=57,
                canonical_story_issue_number=29,
            ),
        ],
        story_task_ids={29: ["issue-56", "issue-57"]},
        work_dependencies=[
            WorkDependency(work_id="issue-57", depends_on_work_id="issue-56"),
        ],
        story_dependencies=[(29, 24)],
        needs_triage_issue_numbers=[60],
    )
    connection = FakeConnection()

    sync_projection_to_control_plane(
        connection=connection,
        repo="codefromkarl/stardrifter",
        projection=projection,
    )

    executed_sql = "\n".join(connection.executed_sql)
    assert "DELETE FROM work_dependency" in executed_sql
    assert "DELETE FROM story_dependency" in executed_sql
    assert "DELETE FROM work_item" in executed_sql
    assert "INSERT INTO work_item" in executed_sql
    assert "INSERT INTO work_dependency" in executed_sql
    assert "INSERT INTO story_dependency" in executed_sql
    assert connection.commits > 0
    assert len(connection.executed_params) >= 4


def test_sync_projection_to_control_plane_deletes_stale_repo_work_items():
    projection = GitHubTaskProjection(
        work_items=[
            WorkItem(
                id="issue-61",
                title="[02-IMPL] fleet logistics/crew/cargo backend runtime skeleton",
                lane="Lane 02",
                wave="unassigned",
                status="pending",
                complexity="medium",
                source_issue_number=61,
                canonical_story_issue_number=24,
                related_story_issue_numbers=(25, 26),
            ),
        ],
        story_task_ids={24: ["issue-61"]},
    )
    connection = FakeConnection()

    sync_projection_to_control_plane(
        connection=connection,
        repo="codefromkarl/stardrifter",
        projection=projection,
    )

    delete_sql = next(
        sql for sql in connection.executed_sql if "DELETE FROM work_item" in sql
    )
    delete_params = next(
        params
        for sql, params in zip(
            connection.executed_sql, connection.executed_params, strict=False
        )
        if "DELETE FROM work_item" in sql
    )

    assert "repo = %s" in delete_sql
    assert "source_issue_number <> ALL(%s)" in delete_sql
    assert delete_params == ("codefromkarl/stardrifter", [61])


def test_sync_projection_to_control_plane_writes_structured_repo_column():
    projection = GitHubTaskProjection(
        work_items=[
            WorkItem(
                id="issue-62",
                title="[02-IMPL] repo column projection",
                lane="Lane 02",
                wave="unassigned",
                status="pending",
                complexity="medium",
                source_issue_number=62,
                canonical_story_issue_number=24,
            ),
        ],
        story_task_ids={24: ["issue-62"]},
    )
    connection = FakeConnection()

    sync_projection_to_control_plane(
        connection=connection,
        repo="codefromkarl/stardrifter",
        projection=projection,
    )

    insert_sql = next(
        sql for sql in connection.executed_sql if "INSERT INTO work_item" in sql
    )
    insert_params = next(
        params
        for sql, params in zip(
            connection.executed_sql, connection.executed_params, strict=False
        )
        if "INSERT INTO work_item" in sql
    )

    assert "repo," in insert_sql
    assert "repo = EXCLUDED.repo" in insert_sql
    insert_params = cast(tuple[object, ...], insert_params)
    assert insert_params[1] == "codefromkarl/stardrifter"


def test_sync_projection_to_control_plane_preserves_existing_work_status():
    projection = GitHubTaskProjection(
        work_items=[
            WorkItem(
                id="issue-56",
                title="[03-DOC] 为 03-C 三条开放项补充 wave 标记与后续 task 跟踪",
                lane="Lane 03",
                wave="unassigned",
                status="pending",
                complexity="low",
                source_issue_number=56,
                canonical_story_issue_number=29,
            ),
        ],
        story_task_ids={29: ["issue-56"]},
    )
    connection = FakeConnection()

    sync_projection_to_control_plane(
        connection=connection,
        repo="codefromkarl/stardrifter",
        projection=projection,
    )

    insert_sql = next(
        sql for sql in connection.executed_sql if "INSERT INTO work_item" in sql
    )

    assert "ON CONFLICT (id) DO UPDATE SET" in insert_sql
    assert "status = work_item.status" in insert_sql
    assert "blocked_reason = work_item.blocked_reason" in insert_sql
    assert "decision_required = work_item.decision_required" in insert_sql


def test_sync_projection_to_control_plane_persists_execution_metadata_columns():
    projection = GitHubTaskProjection(
        work_items=[
            WorkItem(
                id="issue-53",
                title="[04-DOC] 补充 04-A/B/C 子任务 status 标记",
                lane="Lane 04",
                wave="unassigned",
                status="pending",
                complexity="low",
                source_issue_number=53,
                canonical_story_issue_number=30,
                related_story_issue_numbers=(31, 32),
                task_type="documentation",
                blocking_mode="soft",
                planned_paths=(
                    "docs/domains/04-encounter-mediation/execution-plan.md",
                ),
            ),
        ],
        story_task_ids={30: ["issue-53"]},
    )
    connection = FakeConnection()

    sync_projection_to_control_plane(
        connection=connection,
        repo="codefromkarl/stardrifter",
        projection=projection,
    )

    insert_params = next(
        params
        for sql, params in zip(
            connection.executed_sql, connection.executed_params, strict=False
        )
        if "INSERT INTO work_item" in sql
    )
    insert_params = cast(tuple[object, ...], insert_params)
    assert insert_params[8] == 30
    assert insert_params[9] == "documentation"
    assert insert_params[10] == "soft"


def test_sync_projection_to_control_plane_writes_work_targets_for_planned_paths():
    projection = GitHubTaskProjection(
        work_items=[
            WorkItem(
                id="issue-74",
                title="[Wave0-IMPL] register freeze targets",
                lane="Lane INT",
                wave="Wave0",
                status="pending",
                complexity="medium",
                source_issue_number=74,
                canonical_story_issue_number=-1901,
                planned_paths=(
                    "docs/baselines/wave0-freeze.md",
                    "src/taskplane/projection_sync.py",
                ),
            ),
        ],
        story_task_ids={-1901: ["issue-74"]},
    )
    connection = FakeConnection()

    sync_projection_to_control_plane(
        connection=connection,
        repo="codefromkarl/stardrifter",
        projection=projection,
    )

    target_inserts = [
        params
        for sql, params in zip(
            connection.executed_sql, connection.executed_params, strict=False
        )
        if "INSERT INTO work_target" in sql
    ]

    assert len(target_inserts) == 2
    assert target_inserts[0][0] == "issue-74"
    assert target_inserts[0][1] == "docs/baselines/wave0-freeze.md"
    assert target_inserts[1][1] == "src/taskplane/projection_sync.py"


def test_sync_projection_to_control_plane_marks_wave0_frozen_targets():
    projection = GitHubTaskProjection(
        work_items=[
            WorkItem(
                id="issue-90",
                title="[02-IMPL] touches frozen coordinate surface",
                lane="Lane 02",
                wave="Wave0",
                status="pending",
                complexity="medium",
                source_issue_number=90,
                canonical_story_issue_number=25,
                planned_paths=(
                    "docs/authority/active-baselines.md",
                    "data/campaign/authored/campaign_map.json",
                    "src/stardrifter_engine/services/world_query_service.py",
                ),
            ),
        ],
        story_task_ids={25: ["issue-90"]},
    )
    connection = FakeConnection()

    sync_projection_to_control_plane(
        connection=connection,
        repo="codefromkarl/stardrifter",
        projection=projection,
    )

    target_inserts = [
        cast(tuple[object, ...], params)
        for sql, params in zip(
            connection.executed_sql, connection.executed_params, strict=False
        )
        if "INSERT INTO work_target" in sql
    ]

    assert [
        (params[1], params[4], params[5]) for params in target_inserts
    ] == [
        ("docs/authority/active-baselines.md", True, True),
        ("data/campaign/authored/campaign_map.json", True, True),
        ("src/stardrifter_engine/services/world_query_service.py", True, True),
    ]


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection

    def execute(self, sql: str, params=None) -> None:
        self.connection.executed_sql.append(sql)
        self.connection.executed_params.append(params)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


class FakeConnection:
    def __init__(self) -> None:
        self.executed_sql: list[str] = []
        self.executed_params: list[object] = []
        self.commits = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1
