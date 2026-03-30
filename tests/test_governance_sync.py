from stardrifter_orchestration_mvp.github_importer import normalize_github_issue
from stardrifter_orchestration_mvp.governance_sync import (
    build_program_governance_projection,
    sync_program_governance_to_control_plane,
)


def _issue(number: int, title: str, labels: list[str], body: str = ""):
    return normalize_github_issue(
        "codefromkarl/stardrifter",
        {
            "number": number,
            "title": title,
            "body": body,
            "state": "OPEN",
            "url": f"https://github.com/codefromkarl/stardrifter/issues/{number}",
            "labels": [{"name": label} for label in labels],
        },
    )


def test_build_program_governance_projection_assigns_epic_and_story_statuses():
    issues = [
        _issue(13, "[Epic][Lane 01] Campaign Topology 迁移", ["epic", "lane:01", "status:pending"]),
        _issue(19, "[Epic][Wave 0] Freeze 基线锁定", ["epic", "lane:01", "status:pending"]),
        _issue(62, "[Epic][Lane 07] Data Foundation 数据加载层", ["epic", "lane:07", "status:pending"]),
        _issue(21, "[Story][01-A] Authored topology truth 冻结", ["story", "lane:01", "status:pending"], body="Part of #13."),
        _issue(42, "[Story][W0-A] 文档分析与知识蒸馏", ["story", "lane:01", "status:pending"], body="Part of #19."),
        _issue(65, "[Story][01-D] Single Sector Coordinate System 单星区坐标系", ["story", "lane:01", "status:pending", "complexity:low"]),
        _issue(52, "[Story] Lane 新增: characters/officer/skill/ability 系统规划", ["story", "status:pending", "complexity:high"]),
    ]

    projection = build_program_governance_projection(
        repo="codefromkarl/stardrifter",
        issues=issues,
    )

    epic_by_number = {epic.issue_number: epic for epic in projection.epics}
    story_by_number = {story.issue_number: story for story in projection.stories}

    assert epic_by_number[19].program_status == "approved"
    assert epic_by_number[19].execution_status == "active"
    assert epic_by_number[13].execution_status == "gated"
    assert epic_by_number[62].execution_status == "planned"

    assert story_by_number[21].epic_issue_number == 13
    assert story_by_number[21].execution_status == "gated"
    assert story_by_number[42].epic_issue_number == 19
    assert story_by_number[42].execution_status == "decomposing"
    assert story_by_number[65].epic_issue_number == 13
    assert story_by_number[65].program_status == "approved"
    assert story_by_number[52].epic_issue_number is None
    assert story_by_number[52].program_status == "proposed"
    assert story_by_number[52].execution_status == "backlog"


def test_build_program_governance_projection_creates_internal_wave0_governance_story_for_issue_69():
    issues = [
        _issue(19, "[Epic][Wave 0] Freeze 基线锁定", ["epic", "lane:01", "status:pending"]),
        _issue(69, "[Wave0-TASK] 冻结边界定义与签字确认", ["task", "status:pending", "complexity:low"]),
    ]

    projection = build_program_governance_projection(
        repo="codefromkarl/stardrifter",
        issues=issues,
    )

    story_by_number = {story.issue_number: story for story in projection.stories}

    assert -1901 in story_by_number
    assert story_by_number[-1901].epic_issue_number == 19
    assert story_by_number[-1901].program_status == "approved"
    assert story_by_number[-1901].execution_status == "active"
    assert any(dep == (-1901, 42) for dep in projection.story_dependencies) is False


def test_build_program_governance_projection_builds_epic_and_story_dependencies():
    issues = [
        _issue(13, "[Epic][Lane 01] Campaign Topology 迁移", ["epic", "lane:01", "status:pending"]),
        _issue(14, "[Epic][Lane 02] Fleet Simulation 迁移", ["epic", "lane:02", "status:pending"]),
        _issue(19, "[Epic][Wave 0] Freeze 基线锁定", ["epic", "lane:01", "status:pending"]),
        _issue(21, "[Story][01-A] Authored topology truth 冻结", ["story", "lane:01", "status:pending"], body="Part of #13."),
        _issue(22, "[Story][01-B] Canonical geometry 入库", ["story", "lane:01", "status:pending"], body="Part of #13.\n\n## 依赖 Story\n\n- #21\n"),
        _issue(65, "[Story][01-D] Single Sector Coordinate System 单星区坐标系", ["story", "lane:01", "status:pending", "complexity:low"], body="## 依赖\n\n- 依赖 Story 01-A/B/C topology 数据冻结\n- 被 Lane 02 Fleet Movement 依赖\n"),
    ]

    projection = build_program_governance_projection(
        repo="codefromkarl/stardrifter",
        issues=issues,
    )

    assert (13, 19) in projection.epic_dependencies
    assert (22, 21) in projection.story_dependencies


def test_build_program_governance_projection_archives_closed_historical_items():
    issues = [
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 1,
                "title": "[Epic] combat 战斗系统迁移",
                "body": "",
                "state": "CLOSED",
                "url": "https://github.com/codefromkarl/stardrifter/issues/1",
                "labels": [{"name": "epic"}],
            },
        ),
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 43,
                "title": "[Story][W0-B] GitHub Project 结构初始化",
                "body": "Part of #19.",
                "state": "CLOSED",
                "url": "https://github.com/codefromkarl/stardrifter/issues/43",
                "labels": [{"name": "story"}, {"name": "lane:01"}],
            },
        ),
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 19,
                "title": "[Epic][Wave 0] Freeze 基线锁定",
                "body": "",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/19",
                "labels": [{"name": "epic"}, {"name": "lane:01"}, {"name": "status:pending"}],
            },
        ),
    ]

    projection = build_program_governance_projection(
        repo="codefromkarl/stardrifter",
        issues=issues,
    )

    epic_by_number = {epic.issue_number: epic for epic in projection.epics}
    story_by_number = {story.issue_number: story for story in projection.stories}

    assert epic_by_number[1].program_status == "archived"
    assert epic_by_number[1].execution_status == "backlog"
    assert story_by_number[43].program_status == "archived"
    assert story_by_number[43].execution_status == "done"


def test_sync_program_governance_to_control_plane_writes_epics_and_stories():
    projection = build_program_governance_projection(
        repo="codefromkarl/stardrifter",
        issues=[
            _issue(13, "[Epic][Lane 01] Campaign Topology 迁移", ["epic", "lane:01", "status:pending"]),
            _issue(19, "[Epic][Wave 0] Freeze 基线锁定", ["epic", "lane:01", "status:pending"]),
            _issue(21, "[Story][01-A] Authored topology truth 冻结", ["story", "lane:01", "status:pending"], body="Part of #13."),
            _issue(22, "[Story][01-B] Canonical geometry 入库", ["story", "lane:01", "status:pending"], body="Part of #13.\n\n## 依赖 Story\n\n- #21\n"),
            _issue(42, "[Story][W0-A] 文档分析与知识蒸馏", ["story", "lane:01", "status:pending"], body="Part of #19."),
        ],
    )
    connection = FakeConnection()

    sync_program_governance_to_control_plane(
        connection=connection,
        repo="codefromkarl/stardrifter",
        projection=projection,
    )

    executed_sql = "\n".join(connection.executed_sql)
    assert "DELETE FROM program_story_dependency" in executed_sql
    assert "DELETE FROM program_epic_dependency" in executed_sql
    assert "DELETE FROM program_story" in executed_sql
    assert "DELETE FROM program_epic" in executed_sql
    assert "INSERT INTO program_epic" in executed_sql
    assert "INSERT INTO program_story" in executed_sql
    assert "INSERT INTO program_epic_dependency" in executed_sql
    assert "INSERT INTO program_story_dependency" in executed_sql
    assert connection.commits > 0


def test_sync_program_governance_to_control_plane_preserves_existing_execution_status():
    projection = build_program_governance_projection(
        repo="codefromkarl/stardrifter",
        issues=[
            _issue(13, "[Epic][Lane 01] Campaign Topology 迁移", ["epic", "lane:01", "status:pending"]),
            _issue(19, "[Epic][Wave 0] Freeze 基线锁定", ["epic", "lane:01", "status:pending"]),
            _issue(21, "[Story][01-A] Authored topology truth 冻结", ["story", "lane:01", "status:pending"], body="Part of #13."),
            _issue(22, "[Story][01-B] Canonical geometry 入库", ["story", "lane:01", "status:pending"], body="Part of #13.\n\n## 依赖 Story\n\n- #21\n"),
        ],
    )
    connection = FakeConnection(
        fetchall_results=[
            [
                {
                    "issue_number": 13,
                    "program_status": "approved",
                    "execution_status": "active",
                    "active_wave": None,
                    "notes": None,
                },
                {
                    "issue_number": 19,
                    "program_status": "approved",
                    "execution_status": "done",
                    "active_wave": None,
                    "notes": None,
                },
            ],
            [
                {
                    "issue_number": 21,
                    "program_status": "approved",
                    "execution_status": "done",
                    "active_wave": None,
                    "notes": None,
                },
                {
                    "issue_number": 22,
                    "program_status": "approved",
                    "execution_status": "active",
                    "active_wave": None,
                    "notes": None,
                },
            ],
        ]
    )

    sync_program_governance_to_control_plane(
        connection=connection,
        repo="codefromkarl/stardrifter",
        projection=projection,
    )

    story_insert_params = [
        params
        for sql, params in zip(connection.executed_sql, connection.executed_params, strict=False)
        if "INSERT INTO program_story" in sql
    ]
    epic_insert_params = [
        params
        for sql, params in zip(connection.executed_sql, connection.executed_params, strict=False)
        if "INSERT INTO program_epic" in sql
    ]

    assert any(params[5] == "active" for params in epic_insert_params)
    assert any(params[7] == "done" for params in story_insert_params)
    assert any(params[7] == "active" for params in story_insert_params)


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection
        self.last_sql = ""

    def execute(self, sql: str, params=None) -> None:
        self.last_sql = sql
        self.connection.executed_sql.append(sql)
        self.connection.executed_params.append(params)

    def fetchall(self):
        if not self.connection.fetchall_results:
            return []
        return self.connection.fetchall_results.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


class FakeConnection:
    def __init__(self, fetchall_results: list[list[dict[str, object]]] | None = None) -> None:
        self.executed_sql: list[str] = []
        self.executed_params: list[object] = []
        self.commits = 0
        self.fetchall_results = list(fetchall_results or [])

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1
