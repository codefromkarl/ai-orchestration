from pathlib import Path

from stardrifter_orchestration_mvp.models import WorkClaim, WorkItem
from stardrifter_orchestration_mvp.workspace import (
    WorkspaceManager,
    build_workspace_spec,
    ensure_workspace,
)


def test_build_workspace_spec_uses_issue_number_and_slugified_title():
    work_item = WorkItem(
        id="issue-53",
        title="[04-DOC] 补充 04-A/B/C 子任务 status 标记",
        lane="Lane 04",
        wave="unassigned",
        status="pending",
        source_issue_number=53,
    )

    spec = build_workspace_spec(
        work_item=work_item,
        repo_root=Path("/repo/root"),
        worktree_root=Path("/repo/worktrees"),
    )

    assert spec.branch_name == "task/53-04-doc"
    assert spec.workspace_path == Path("/repo/worktrees/task-53-04-doc")


def test_build_workspace_spec_uses_canonical_story_boundary_when_available():
    work_item = WorkItem(
        id="issue-70",
        title="[01-DOC] 建立 lane 参考映射",
        lane="Lane 01",
        wave="wave-1",
        status="pending",
        source_issue_number=70,
        canonical_story_issue_number=42,
    )

    spec = build_workspace_spec(
        work_item=work_item,
        repo_root=Path("/repo/root"),
        worktree_root=Path("/repo/worktrees"),
    )

    assert spec.branch_name == "story/42"
    assert spec.workspace_path == Path("/repo/worktrees/story-42")


def test_ensure_workspace_runs_git_worktree_add():
    work_item = WorkItem(
        id="issue-53",
        title="[04-DOC] 补充 04-A/B/C 子任务 status 标记",
        lane="Lane 04",
        wave="unassigned",
        status="pending",
        source_issue_number=53,
    )
    commands: list[list[str]] = []

    def fake_runner(command: list[str]) -> None:
        commands.append(command)

    spec = ensure_workspace(
        work_item=work_item,
        repo_root=Path("/repo/root"),
        worktree_root=Path("/repo/worktrees"),
        base_branch="main",
        runner=fake_runner,
    )

    assert spec.branch_name == "task/53-04-doc"
    assert commands == [
        [
            "git",
            "-C",
            "/repo/root",
            "worktree",
            "add",
            "-b",
            "task/53-04-doc",
            "/repo/worktrees/task-53-04-doc",
            "main",
        ]
    ]


def test_ensure_workspace_uses_story_branch_when_work_item_belongs_to_story():
    work_item = WorkItem(
        id="issue-71",
        title="[01-DOC] 回填 domain README",
        lane="Lane 01",
        wave="wave-1",
        status="pending",
        source_issue_number=71,
        canonical_story_issue_number=42,
    )
    commands: list[list[str]] = []

    def fake_runner(command: list[str]) -> None:
        commands.append(command)

    spec = ensure_workspace(
        work_item=work_item,
        repo_root=Path("/repo/root"),
        worktree_root=Path("/repo/worktrees"),
        base_branch="main",
        runner=fake_runner,
    )

    assert spec.branch_name == "story/42"
    assert commands == [
        [
            "git",
            "-C",
            "/repo/root",
            "worktree",
            "add",
            "-b",
            "story/42",
            "/repo/worktrees/story-42",
            "main",
        ]
    ]


def test_ensure_workspace_reuses_existing_story_branch_without_creating_branch_again():
    work_item = WorkItem(
        id="issue-69",
        title="[Wave0-TASK] 冻结边界定义与签字确认",
        lane="Lane 01",
        wave="unassigned",
        status="pending",
        source_issue_number=69,
        canonical_story_issue_number=42,
    )
    commands: list[list[str]] = []

    def fake_runner(command: list[str]) -> None:
        commands.append(command)

    spec = ensure_workspace(
        work_item=work_item,
        repo_root=Path("/repo/root"),
        worktree_root=Path("/repo/worktrees"),
        base_branch="main",
        runner=fake_runner,
        branch_exists=lambda repo_root, branch_name: branch_name == "story/42",
    )

    assert spec.branch_name == "story/42"
    assert commands == [
        [
            "git",
            "-C",
            "/repo/root",
            "worktree",
            "add",
            "/repo/worktrees/story-42",
            "story/42",
        ]
    ]


def test_workspace_manager_prepare_does_not_write_claim(tmp_path):
    work_item = WorkItem(
        id="issue-53",
        title="[04-DOC] 补充 04-A/B/C 子任务 status 标记",
        lane="Lane 04",
        wave="unassigned",
        status="pending",
        source_issue_number=53,
        planned_paths=("docs/domains/04-encounter-mediation/",),
    )
    commands: list[list[str]] = []
    claims: list[WorkClaim] = []

    class FakeRepository:
        def upsert_work_claim(self, claim: WorkClaim) -> None:
            claims.append(claim)

        def delete_work_claim(self, work_id: str) -> None:
            raise AssertionError("delete should not be called during prepare")

    manager = WorkspaceManager(
        repo_root=Path("/repo/root"),
        worktree_root=tmp_path,
        base_branch="main",
        runner=commands.append,
    )

    workspace_path = manager.prepare(
        work_item=work_item,
        worker_name="worker-a",
        repository=FakeRepository(),
    )

    assert workspace_path == tmp_path / "task-53-04-doc"
    assert claims == []
    assert commands == [
        [
            "git",
            "-C",
            "/repo/root",
            "worktree",
            "add",
            "-b",
            "task/53-04-doc",
            str(tmp_path / "task-53-04-doc"),
            "main",
        ]
    ]
