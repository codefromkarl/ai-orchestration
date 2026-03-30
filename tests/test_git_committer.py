from __future__ import annotations

import subprocess

from stardrifter_orchestration_mvp.git_committer import (
    build_git_committer,
    build_git_story_integrator,
)
from stardrifter_orchestration_mvp.models import WorkItem
from stardrifter_orchestration_mvp.worker import ExecutionResult


def _init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return repo


def test_git_committer_commits_changed_paths_with_task_number(tmp_path):
    repo = _init_repo(tmp_path)
    target = repo / "notes.md"
    target.write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.md"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    target.write_text("v2\n", encoding="utf-8")
    committer = build_git_committer(workdir=repo)
    result = committer(
        WorkItem(
            id="issue-60",
            title="process task",
            lane="Lane 01",
            wave="unassigned",
            status="verifying",
            source_issue_number=60,
        ),
        ExecutionResult(
            success=True,
            summary="updated docs",
            result_payload_json={"changed_paths": ["notes.md"], "preexisting_dirty_paths": []},
        ),
    )

    assert result.committed is True
    assert result.commit_sha is not None
    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%B"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "task-60" in log
    assert "#60" in log


def test_git_committer_skips_commit_when_no_changed_paths(tmp_path):
    repo = _init_repo(tmp_path)
    committer = build_git_committer(workdir=repo)
    result = committer(
        WorkItem(
            id="issue-44",
            title="already satisfied",
            lane="Lane 01",
            wave="unassigned",
            status="verifying",
            source_issue_number=44,
        ),
        ExecutionResult(
            success=True,
            summary="no-op",
            result_payload_json={"changed_paths": [], "preexisting_dirty_paths": []},
        ),
    )

    assert result.committed is False
    assert result.blocked_reason is None


def test_git_committer_blocks_when_changed_path_was_already_dirty(tmp_path):
    repo = _init_repo(tmp_path)
    target = repo / "notes.md"
    target.write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.md"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    target.write_text("user change\n", encoding="utf-8")
    target.write_text("user change\nagent change\n", encoding="utf-8")
    committer = build_git_committer(workdir=repo)
    result = committer(
        WorkItem(
            id="issue-47",
            title="mixed task",
            lane="Lane 02",
            wave="unassigned",
            status="verifying",
            source_issue_number=47,
        ),
        ExecutionResult(
            success=True,
            summary="changed dirty file",
            result_payload_json={"changed_paths": ["notes.md"], "preexisting_dirty_paths": ["notes.md"]},
        ),
    )

    assert result.committed is False
    assert result.blocked_reason == "unsafe_auto_commit_dirty_paths"


def test_git_story_integrator_merges_story_branch_into_main(tmp_path):
    repo = _init_repo(tmp_path)
    target = repo / "notes.md"
    target.write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.md"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "checkout", "-b", "story/42"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    target.write_text("v2\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.md"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "story change"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "checkout", "master"], cwd=repo, check=True, capture_output=True, text=True)

    integrator = build_git_story_integrator(repo_root=repo, base_branch="master")
    result = integrator(
        story_issue_number=42,
        story_work_items=[
            WorkItem(
                id="issue-70",
                title="task 70",
                lane="Lane 01",
                wave="wave-1",
                status="done",
                source_issue_number=70,
                canonical_story_issue_number=42,
            )
        ],
    )

    assert result.merged is True
    assert result.merge_commit_sha is not None
    assert "story/42" in subprocess.run(
        ["git", "log", "-1", "--pretty=%B"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_git_story_integrator_ignores_worktree_facility_directory_when_checking_dirty_base(tmp_path):
    repo = _init_repo(tmp_path)
    target = repo / "notes.md"
    target.write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.md"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "checkout", "-b", "story/42"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    target.write_text("v2\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.md"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "story change"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "checkout", "master"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / ".orchestration-worktrees").mkdir()

    integrator = build_git_story_integrator(
        repo_root=repo,
        base_branch="master",
        ignored_dirty_path_prefixes=(".orchestration-worktrees/",),
    )
    result = integrator(
        story_issue_number=42,
        story_work_items=[
            WorkItem(
                id="issue-70",
                title="task 70",
                lane="Lane 01",
                wave="wave-1",
                status="done",
                source_issue_number=70,
                canonical_story_issue_number=42,
            )
        ],
    )

    assert result.merged is True
    assert result.blocked_reason is None


def test_git_story_integrator_promotes_merged_story_into_target_repo(tmp_path):
    execution_root = tmp_path / "execution-root"
    execution_root.mkdir()
    execution_repo = _init_repo(execution_root)
    target = execution_repo / "notes.md"
    target.write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.md"], cwd=execution_repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=execution_repo, check=True, capture_output=True, text=True)
    promotion_repo = tmp_path / "promotion-repo"
    subprocess.run(
        ["git", "clone", str(execution_repo), str(promotion_repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "checkout", "-b", "story/42"],
        cwd=execution_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    target.write_text("v2\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.md"], cwd=execution_repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "story change"], cwd=execution_repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "checkout", "master"], cwd=execution_repo, check=True, capture_output=True, text=True)

    integrator = build_git_story_integrator(
        repo_root=execution_repo,
        base_branch="master",
        promotion_repo_root=promotion_repo,
        promotion_base_branch="master",
    )
    result = integrator(
        story_issue_number=42,
        story_work_items=[
            WorkItem(
                id="issue-70",
                title="task 70",
                lane="Lane 01",
                wave="wave-1",
                status="done",
                source_issue_number=70,
                canonical_story_issue_number=42,
            )
        ],
    )

    assert result.merged is True
    assert result.promoted is True
    assert result.promotion_commit_sha is not None
    assert (promotion_repo / "notes.md").read_text(encoding="utf-8") == "v2\n"
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=promotion_repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == result.promotion_commit_sha
    )


def test_git_story_integrator_promotes_even_when_story_branch_is_already_merged(tmp_path):
    execution_root = tmp_path / "execution-root"
    execution_root.mkdir()
    execution_repo = _init_repo(execution_root)
    target = execution_repo / "notes.md"
    target.write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.md"], cwd=execution_repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=execution_repo, check=True, capture_output=True, text=True)
    promotion_repo = tmp_path / "promotion-repo"
    subprocess.run(
        ["git", "clone", str(execution_repo), str(promotion_repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "checkout", "-b", "story/42"],
        cwd=execution_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    target.write_text("v2\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.md"], cwd=execution_repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "story change"], cwd=execution_repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "checkout", "master"], cwd=execution_repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "merge", "--no-ff", "--no-edit", "story/42"], cwd=execution_repo, check=True, capture_output=True, text=True)

    integrator = build_git_story_integrator(
        repo_root=execution_repo,
        base_branch="master",
        promotion_repo_root=promotion_repo,
        promotion_base_branch="master",
    )
    result = integrator(
        story_issue_number=42,
        story_work_items=[
            WorkItem(
                id="issue-70",
                title="task 70",
                lane="Lane 01",
                wave="wave-1",
                status="done",
                source_issue_number=70,
                canonical_story_issue_number=42,
            )
        ],
    )

    assert result.merged is True
    assert result.promoted is True
    assert (promotion_repo / "notes.md").read_text(encoding="utf-8") == "v2\n"
