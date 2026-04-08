from pathlib import Path
import subprocess

from taskplane.models import WorkClaim, WorkItem
from taskplane.workspace import (
    WorkspaceManager,
    _is_excluded_dirty_path,
    _list_claimed_dirty_paths,
    _list_dirty_support_paths,
    _sync_claimed_dirty_paths,
    _sync_support_dirty_paths,
    build_workspace_spec,
    ensure_workspace,
    resolve_base_branch,
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


def test_ensure_workspace_auto_detects_current_branch_when_base_branch_is_omitted(
    monkeypatch,
):
    work_item = WorkItem(
        id="issue-53",
        title="[04-DOC] 补充 04-A/B/C 子任务 status 标记",
        lane="Lane 04",
        wave="unassigned",
        status="pending",
        source_issue_number=53,
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "taskplane.workspace.resolve_base_branch",
        lambda repo_root: "master",
    )

    ensure_workspace(
        work_item=work_item,
        repo_root=Path("/repo/root"),
        worktree_root=Path("/repo/worktrees"),
        runner=commands.append,
    )

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
            "master",
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


def test_ensure_workspace_returns_existing_workspace_without_running_git(tmp_path):
    worktree_root = tmp_path / "worktrees"
    existing_workspace = worktree_root / "story-42"
    existing_workspace.mkdir(parents=True)
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
        worktree_root=worktree_root,
        base_branch="main",
        runner=fake_runner,
        branch_exists=lambda repo_root, branch_name: (_ for _ in ()).throw(
            AssertionError("branch lookup should be skipped for existing workspace")
        ),
    )

    assert spec.workspace_path == existing_workspace
    assert commands == []


def test_workspace_manager_prewarm_only_creates_story_workspace_once(tmp_path):
    commands: list[list[str]] = []
    manager = WorkspaceManager(
        repo_root=Path("/repo/root"),
        worktree_root=tmp_path,
        base_branch="main",
        runner=commands.append,
    )
    story_task_a = WorkItem(
        id="issue-80",
        title="[01-IMPL] Story task A",
        lane="Lane 01",
        wave="wave-1",
        status="ready",
        source_issue_number=80,
        canonical_story_issue_number=42,
    )
    story_task_b = WorkItem(
        id="issue-81",
        title="[01-IMPL] Story task B",
        lane="Lane 01",
        wave="wave-1",
        status="ready",
        source_issue_number=81,
        canonical_story_issue_number=42,
    )
    standalone_task = WorkItem(
        id="issue-82",
        title="[01-IMPL] Standalone task",
        lane="Lane 01",
        wave="wave-1",
        status="ready",
        source_issue_number=82,
    )

    warmed = manager.prewarm(work_items=[story_task_a, story_task_b, standalone_task])

    assert warmed == [tmp_path / "story-42"]
    assert commands == [
        [
            "git",
            "-C",
            "/repo/root",
            "worktree",
            "add",
            "-b",
            "story/42",
            str(tmp_path / "story-42"),
            "main",
        ]
    ]


def test_resolve_base_branch_prefers_current_branch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "checkout", "-b", "master"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    assert resolve_base_branch(repo) == "master"


def test_list_dirty_support_paths_skips_planned_and_internal_paths(monkeypatch):
    monkeypatch.setattr(
        "taskplane.workspace._git_porcelain_paths",
        lambda repo_root: [
            Path("lib/support_model.dart"),
            Path("lib/features/run_flow/run_flow_controller.dart"),
            Path(".taskplane/worktrees/story-176/tmp.txt"),
        ],
    )

    paths = _list_dirty_support_paths(
        repo_root=Path("/repo/root"),
        excluded_paths=("lib/features/run_flow/run_flow_controller.dart",),
    )

    assert paths == [Path("lib/support_model.dart")]


def test_list_claimed_dirty_paths_returns_only_planned_dirty_paths(monkeypatch):
    monkeypatch.setattr(
        "taskplane.workspace._git_porcelain_paths",
        lambda repo_root: [
            Path("lib/support_model.dart"),
            Path("lib/features/run_flow/run_flow_controller.dart"),
            Path(".taskplane/worktrees/story-176/tmp.txt"),
        ],
    )

    paths = _list_claimed_dirty_paths(
        repo_root=Path("/repo/root"),
        claimed_paths=("lib/features/run_flow/run_flow_controller.dart",),
    )

    assert paths == [Path("lib/features/run_flow/run_flow_controller.dart")]


def test_sync_support_dirty_paths_copies_non_task_dirty_files(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    workspace = tmp_path / "worktree"
    (repo_root / "lib").mkdir(parents=True)
    workspace.mkdir(parents=True)
    (repo_root / "lib" / "support_model.dart").write_text(
        "class SupportModel {}\n",
        encoding="utf-8",
    )
    (repo_root / "lib" / "run_flow_controller.dart").write_text(
        "class DirtyTaskFile {}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "taskplane.workspace._list_dirty_support_paths",
        lambda repo_root, excluded_paths: [
            Path("lib/support_model.dart"),
        ],
    )

    _sync_support_dirty_paths(
        repo_root=repo_root,
        workspace_path=workspace,
        work_item=WorkItem(
            id="task-1",
            title="sync support files",
            lane="Lane 01",
            wave="unassigned",
            status="pending",
            planned_paths=("lib/run_flow_controller.dart",),
            source_issue_number=1,
        ),
    )

    assert (workspace / "lib" / "support_model.dart").read_text(encoding="utf-8") == (
        "class SupportModel {}\n"
    )
    assert not (workspace / "lib" / "run_flow_controller.dart").exists()


def test_sync_claimed_dirty_paths_copies_only_task_dirty_files(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    workspace = tmp_path / "worktree"
    (repo_root / "lib" / "features" / "run_flow").mkdir(parents=True)
    workspace.mkdir(parents=True)
    (repo_root / "lib" / "features" / "run_flow" / "run_flow_controller.dart").write_text(
        "class DirtyTaskFile {}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "taskplane.workspace._list_claimed_dirty_paths",
        lambda repo_root, claimed_paths: [
            Path("lib/features/run_flow/run_flow_controller.dart"),
        ],
    )

    _sync_claimed_dirty_paths(
        repo_root=repo_root,
        workspace_path=workspace,
        work_item=WorkItem(
            id="task-1",
            title="sync claimed files",
            lane="Lane 01",
            wave="unassigned",
            status="pending",
            planned_paths=("lib/features/run_flow/run_flow_controller.dart",),
            source_issue_number=1,
        ),
    )

    assert (
        workspace / "lib" / "features" / "run_flow" / "run_flow_controller.dart"
    ).read_text(encoding="utf-8") == "class DirtyTaskFile {}\n"


def test_is_excluded_dirty_path_matches_file_and_directory_prefixes():
    assert _is_excluded_dirty_path(
        "lib/features/run_flow/run_flow_controller.dart",
        ("lib/features/run_flow/run_flow_controller.dart",),
    )
    assert _is_excluded_dirty_path(
        "lib/features/run_flow/sub/item.dart",
        ("lib/features/run_flow/",),
    )
    assert not _is_excluded_dirty_path(
        "lib/shared/widgets/run_layer_timeline.dart",
        ("lib/features/run_flow/",),
    )


def test_workspace_manager_prepare_reuses_prewarmed_story_workspace(tmp_path):
    commands: list[list[str]] = []

    class FakeRepository:
        def delete_work_claim(self, work_id: str) -> None:
            del work_id

    manager = WorkspaceManager(
        repo_root=Path("/repo/root"),
        worktree_root=tmp_path,
        base_branch="main",
        runner=commands.append,
    )
    work_item = WorkItem(
        id="issue-83",
        title="[01-IMPL] Story task",
        lane="Lane 01",
        wave="wave-1",
        status="ready",
        source_issue_number=83,
        canonical_story_issue_number=42,
    )

    warmed = manager.prewarm(work_items=[work_item])
    workspace_path = manager.prepare(
        work_item=work_item,
        worker_name="worker-a",
        repository=FakeRepository(),
    )

    assert warmed == [tmp_path / "story-42"]
    assert workspace_path == tmp_path / "story-42"
    assert commands == [
        [
            "git",
            "-C",
            "/repo/root",
            "worktree",
            "add",
            "-b",
            "story/42",
            str(tmp_path / "story-42"),
            "main",
        ]
    ]
