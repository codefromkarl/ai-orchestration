from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time

from taskplane.contextweaver_indexing import (
    CheckoutAliasRecord,
    FileIndexRegistry,
    IndexArtifactRecord,
    RepositoryIdentity,
    SnapshotObservation,
    ensure_contextweaver_index_for_checkout,
    resolve_repository_identity,
)


def test_resolve_repository_identity_prefers_explicit_repo(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    monkeypatch.setattr(
        "taskplane.contextweaver_indexing._resolve_git_root",
        lambda project_dir: repo_root,
    )
    monkeypatch.setattr(
        "taskplane.contextweaver_indexing._git_stdout",
        lambda repo_root, args: "abc123\n" if args == ["rev-parse", "HEAD"] else "",
    )

    identity = resolve_repository_identity(
        tmp_path,
        explicit_repo="codefromkarl/stardrifter",
    )

    assert identity.repository_id == "control:codefromkarl/stardrifter"
    assert identity.snapshot_id == "abc123"
    assert identity.repo_root == repo_root
    assert identity.is_dirty is False


def test_resolve_repository_identity_marks_dirty_snapshot(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    monkeypatch.setattr(
        "taskplane.contextweaver_indexing._resolve_git_root",
        lambda project_dir: repo_root,
    )

    def fake_git_stdout(repo_root, args):
        if args == ["rev-parse", "HEAD"]:
            return "deadbeef\n"
        if args == ["status", "--porcelain"]:
            return " M src/file.py\n"
        if args == ["diff", "--no-ext-diff", "--binary", "HEAD"]:
            return "diff --git a/src/file.py b/src/file.py\n+new line\n"
        raise AssertionError(args)

    monkeypatch.setattr(
        "taskplane.contextweaver_indexing._git_stdout",
        fake_git_stdout,
    )

    identity = resolve_repository_identity(tmp_path, explicit_repo="repo")

    assert identity.is_dirty is True
    assert identity.snapshot_id.startswith("deadbeef:dirty:")
    assert identity.dirty_fingerprint is not None


def test_resolve_repository_identity_reuses_same_dirty_fingerprint_for_same_changes(
    monkeypatch, tmp_path
):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    monkeypatch.setattr(
        "taskplane.contextweaver_indexing._resolve_git_root",
        lambda project_dir: repo_root,
    )

    def fake_git_stdout(repo_root, args):
        if args == ["rev-parse", "HEAD"]:
            return "deadbeef\n"
        if args == ["status", "--porcelain"]:
            return " M src/file.py\n"
        if args == ["diff", "--no-ext-diff", "--binary", "HEAD"]:
            return "diff --git a/src/file.py b/src/file.py\n+new line\n"
        raise AssertionError(args)

    monkeypatch.setattr(
        "taskplane.contextweaver_indexing._git_stdout",
        fake_git_stdout,
    )

    first = resolve_repository_identity(tmp_path, explicit_repo="repo")
    second = resolve_repository_identity(tmp_path, explicit_repo="repo")

    assert first.dirty_fingerprint is not None
    assert second.dirty_fingerprint is not None
    assert first.dirty_fingerprint == second.dirty_fingerprint
    assert first.snapshot_id == second.snapshot_id


def test_resolve_repository_identity_changes_dirty_snapshot_for_different_changes(
    monkeypatch, tmp_path
):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    diff_output = {"value": "diff --git a/src/file.py b/src/file.py\n+line one\n"}

    monkeypatch.setattr(
        "taskplane.contextweaver_indexing._resolve_git_root",
        lambda project_dir: repo_root,
    )

    def fake_git_stdout(repo_root, args):
        if args == ["rev-parse", "HEAD"]:
            return "deadbeef\n"
        if args == ["status", "--porcelain"]:
            return " M src/file.py\n"
        if args == ["diff", "--no-ext-diff", "--binary", "HEAD"]:
            return diff_output["value"]
        raise AssertionError(args)

    monkeypatch.setattr(
        "taskplane.contextweaver_indexing._git_stdout",
        fake_git_stdout,
    )

    first = resolve_repository_identity(tmp_path, explicit_repo="repo")
    diff_output["value"] = "diff --git a/src/file.py b/src/file.py\n+line two\n"
    second = resolve_repository_identity(tmp_path, explicit_repo="repo")

    assert first.snapshot_id != second.snapshot_id
    assert first.dirty_fingerprint != second.dirty_fingerprint


def test_ensure_contextweaver_index_for_checkout_reuses_ready_snapshot_record(
    monkeypatch, tmp_path
):
    calls: list[Path] = []
    registry_path = tmp_path / "registry.json"
    registry = FileIndexRegistry(registry_path)
    registry.record_checkout_alias(
        CheckoutAliasRecord(
            checkout_path=str(tmp_path / "existing-checkout"),
            repository_id="control:repo",
            snapshot_id="abc123",
            repo_root=str(tmp_path / "repo"),
        )
    )
    registry.upsert_artifact(
        IndexArtifactRecord(
            repository_id="control:repo",
            snapshot_id="abc123",
            repo_root=str(tmp_path / "repo"),
            schema_version="v1",
            status="ready",
        )
    )

    monkeypatch.setattr(
        "taskplane.contextweaver_indexing.resolve_repository_identity",
        lambda project_dir, explicit_repo=None: RepositoryIdentity(
            project_dir=project_dir.resolve(),
            repo_root=(tmp_path / "repo").resolve(),
            repository_id="control:repo",
            head_sha="abc123",
            is_dirty=False,
            snapshot_id="abc123",
        ),
    )
    monkeypatch.setattr(
        "taskplane.contextweaver_indexing._run_contextweaver_index",
        lambda project_dir: calls.append(project_dir) or None,
    )

    result = ensure_contextweaver_index_for_checkout(
        tmp_path / "fresh-checkout",
        explicit_repo="repo",
        registry=registry,
    )

    assert result is None
    assert calls == []
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    aliases = payload["checkout_aliases"]
    assert str((tmp_path / "fresh-checkout").resolve()) in aliases


def test_ensure_contextweaver_index_for_checkout_indexes_on_registry_miss(
    monkeypatch, tmp_path
):
    calls: list[Path] = []
    registry = FileIndexRegistry(tmp_path / "registry.json")

    monkeypatch.setattr(
        "taskplane.contextweaver_indexing.resolve_repository_identity",
        lambda project_dir, explicit_repo=None: RepositoryIdentity(
            project_dir=project_dir.resolve(),
            repo_root=(tmp_path / "repo").resolve(),
            repository_id="control:repo",
            head_sha="abc123",
            is_dirty=False,
            snapshot_id="abc123",
        ),
    )
    monkeypatch.setattr(
        "taskplane.contextweaver_indexing._run_contextweaver_index",
        lambda project_dir: calls.append(project_dir) or None,
    )

    result = ensure_contextweaver_index_for_checkout(
        tmp_path / "fresh-checkout",
        explicit_repo="repo",
        registry=registry,
    )

    assert result is None
    assert calls == [(tmp_path / "fresh-checkout").resolve()]
    artifact = registry.get_artifact(
        repository_id="control:repo",
        snapshot_id="abc123",
        schema_version="v1",
    )
    assert artifact is not None
    assert artifact.status == "ready"


def test_ensure_contextweaver_index_for_checkout_can_be_skipped_by_env(
    monkeypatch, tmp_path
):
    called = False

    def fake_run(project_dir):
        nonlocal called
        called = True
        raise AssertionError("contextweaver index should have been skipped")

    monkeypatch.setenv("TASKPLANE_SKIP_CONTEXTWEAVER_INDEX", "true")
    monkeypatch.setattr(
        "taskplane.contextweaver_indexing._run_contextweaver_index",
        fake_run,
    )

    result = ensure_contextweaver_index_for_checkout(tmp_path, explicit_repo="repo")

    assert result is None
    assert called is False


def test_ensure_contextweaver_index_for_checkout_does_not_duplicate_build_when_lock_exists(
    monkeypatch, tmp_path
):
    calls: list[Path] = []
    registry = FileIndexRegistry(tmp_path / "registry.json")
    identity = RepositoryIdentity(
        project_dir=(tmp_path / "fresh-checkout").resolve(),
        repo_root=(tmp_path / "repo").resolve(),
        repository_id="control:repo",
        head_sha="abc123",
        is_dirty=False,
        snapshot_id="abc123",
        dirty_fingerprint=None,
    )

    monkeypatch.setattr(
        "taskplane.contextweaver_indexing.resolve_repository_identity",
        lambda project_dir, explicit_repo=None: identity,
    )
    monkeypatch.setattr(
        "taskplane.contextweaver_indexing._run_contextweaver_index",
        lambda project_dir: calls.append(project_dir) or None,
    )
    monkeypatch.setenv("TASKPLANE_CONTEXTWEAVER_LOCK_WAIT_SECONDS", "0.03")
    monkeypatch.setenv("TASKPLANE_CONTEXTWEAVER_LOCK_POLL_SECONDS", "0.01")

    lock_path = registry.lock_path_for_artifact(
        repository_id="control:repo",
        snapshot_id="abc123",
        schema_version="v1",
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("held", encoding="utf-8")

    result = ensure_contextweaver_index_for_checkout(
        tmp_path / "fresh-checkout",
        explicit_repo="repo",
        registry=registry,
    )

    assert result == "timed out waiting for contextweaver snapshot build lock"
    assert calls == []


def test_ensure_contextweaver_index_for_checkout_waits_for_ready_artifact_when_lock_exists(
    monkeypatch, tmp_path
):
    calls: list[Path] = []
    registry = FileIndexRegistry(tmp_path / "registry.json")
    identity = RepositoryIdentity(
        project_dir=(tmp_path / "fresh-checkout").resolve(),
        repo_root=(tmp_path / "repo").resolve(),
        repository_id="control:repo",
        head_sha="abc123",
        is_dirty=False,
        snapshot_id="abc123",
        dirty_fingerprint=None,
    )

    monkeypatch.setattr(
        "taskplane.contextweaver_indexing.resolve_repository_identity",
        lambda project_dir, explicit_repo=None: identity,
    )
    monkeypatch.setattr(
        "taskplane.contextweaver_indexing._run_contextweaver_index",
        lambda project_dir: calls.append(project_dir) or None,
    )
    monkeypatch.setenv("TASKPLANE_CONTEXTWEAVER_LOCK_WAIT_SECONDS", "0.2")
    monkeypatch.setenv("TASKPLANE_CONTEXTWEAVER_LOCK_POLL_SECONDS", "0.01")

    lock_path = registry.lock_path_for_artifact(
        repository_id="control:repo",
        snapshot_id="abc123",
        schema_version="v1",
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("held", encoding="utf-8")

    def mark_ready_after_delay() -> None:
        time.sleep(0.03)
        registry.upsert_artifact(
            IndexArtifactRecord(
                repository_id="control:repo",
                snapshot_id="abc123",
                repo_root=str((tmp_path / "repo").resolve()),
                schema_version="v1",
                status="ready",
            )
        )
        lock_path.unlink(missing_ok=True)

    thread = threading.Thread(target=mark_ready_after_delay)
    thread.start()
    try:
        result = ensure_contextweaver_index_for_checkout(
            tmp_path / "fresh-checkout",
            explicit_repo="repo",
            registry=registry,
        )
    finally:
        thread.join()

    assert result is None
    assert calls == []


def test_ensure_contextweaver_index_for_checkout_returns_failed_artifact_error_after_wait(
    monkeypatch, tmp_path
):
    calls: list[Path] = []
    registry = FileIndexRegistry(tmp_path / "registry.json")
    identity = RepositoryIdentity(
        project_dir=(tmp_path / "fresh-checkout").resolve(),
        repo_root=(tmp_path / "repo").resolve(),
        repository_id="control:repo",
        head_sha="abc123",
        is_dirty=False,
        snapshot_id="abc123",
        dirty_fingerprint=None,
    )

    monkeypatch.setattr(
        "taskplane.contextweaver_indexing.resolve_repository_identity",
        lambda project_dir, explicit_repo=None: identity,
    )
    monkeypatch.setattr(
        "taskplane.contextweaver_indexing._run_contextweaver_index",
        lambda project_dir: calls.append(project_dir) or None,
    )
    monkeypatch.setenv("TASKPLANE_CONTEXTWEAVER_LOCK_WAIT_SECONDS", "0.2")
    monkeypatch.setenv("TASKPLANE_CONTEXTWEAVER_LOCK_POLL_SECONDS", "0.01")

    lock_path = registry.lock_path_for_artifact(
        repository_id="control:repo",
        snapshot_id="abc123",
        schema_version="v1",
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("held", encoding="utf-8")

    def mark_failed_after_delay() -> None:
        time.sleep(0.03)
        registry.upsert_artifact(
            IndexArtifactRecord(
                repository_id="control:repo",
                snapshot_id="abc123",
                repo_root=str((tmp_path / "repo").resolve()),
                schema_version="v1",
                status="failed",
                last_error="upstream build failed",
            )
        )
        lock_path.unlink(missing_ok=True)

    thread = threading.Thread(target=mark_failed_after_delay)
    thread.start()
    try:
        result = ensure_contextweaver_index_for_checkout(
            tmp_path / "fresh-checkout",
            explicit_repo="repo",
            registry=registry,
        )
    finally:
        thread.join()

    assert result == "upstream build failed"
    assert calls == []


def test_ensure_contextweaver_index_for_checkout_times_out_waiting_for_inflight_build(
    monkeypatch, tmp_path
):
    calls: list[Path] = []
    registry = FileIndexRegistry(tmp_path / "registry.json")
    identity = RepositoryIdentity(
        project_dir=(tmp_path / "fresh-checkout").resolve(),
        repo_root=(tmp_path / "repo").resolve(),
        repository_id="control:repo",
        head_sha="abc123",
        is_dirty=False,
        snapshot_id="abc123",
        dirty_fingerprint=None,
    )

    monkeypatch.setattr(
        "taskplane.contextweaver_indexing.resolve_repository_identity",
        lambda project_dir, explicit_repo=None: identity,
    )
    monkeypatch.setattr(
        "taskplane.contextweaver_indexing._run_contextweaver_index",
        lambda project_dir: calls.append(project_dir) or None,
    )
    monkeypatch.setenv("TASKPLANE_CONTEXTWEAVER_LOCK_WAIT_SECONDS", "0.03")
    monkeypatch.setenv("TASKPLANE_CONTEXTWEAVER_LOCK_POLL_SECONDS", "0.01")

    lock_path = registry.lock_path_for_artifact(
        repository_id="control:repo",
        snapshot_id="abc123",
        schema_version="v1",
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("held", encoding="utf-8")

    result = ensure_contextweaver_index_for_checkout(
        tmp_path / "fresh-checkout",
        explicit_repo="repo",
        registry=registry,
    )

    assert result == "timed out waiting for contextweaver snapshot build lock"
    assert calls == []


def test_ensure_contextweaver_index_for_checkout_reclaims_stale_build_lock_and_indexes(
    monkeypatch, tmp_path
):
    calls: list[Path] = []
    registry = FileIndexRegistry(tmp_path / "registry.json")
    identity = RepositoryIdentity(
        project_dir=(tmp_path / "fresh-checkout").resolve(),
        repo_root=(tmp_path / "repo").resolve(),
        repository_id="control:repo",
        head_sha="abc123",
        is_dirty=False,
        snapshot_id="abc123",
        dirty_fingerprint=None,
    )

    monkeypatch.setattr(
        "taskplane.contextweaver_indexing.resolve_repository_identity",
        lambda project_dir, explicit_repo=None: identity,
    )
    monkeypatch.setattr(
        "taskplane.contextweaver_indexing._run_contextweaver_index",
        lambda project_dir: calls.append(project_dir) or None,
    )
    monkeypatch.setenv("TASKPLANE_CONTEXTWEAVER_LOCK_STALE_SECONDS", "0.01")

    lock_path = registry.lock_path_for_artifact(
        repository_id="control:repo",
        snapshot_id="abc123",
        schema_version="v1",
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("held", encoding="utf-8")
    stale_time = time.time() - 5
    os.utime(lock_path, (stale_time, stale_time))

    result = ensure_contextweaver_index_for_checkout(
        tmp_path / "fresh-checkout",
        explicit_repo="repo",
        registry=registry,
    )

    assert result is None
    assert calls == [(tmp_path / "fresh-checkout").resolve()]
    artifact = registry.get_artifact(
        repository_id="control:repo",
        snapshot_id="abc123",
        schema_version="v1",
    )
    assert artifact is not None
    assert artifact.status == "ready"


def test_ensure_contextweaver_index_for_checkout_preserves_fresh_build_lock(
    monkeypatch, tmp_path
):
    calls: list[Path] = []
    registry = FileIndexRegistry(tmp_path / "registry.json")
    identity = RepositoryIdentity(
        project_dir=(tmp_path / "fresh-checkout").resolve(),
        repo_root=(tmp_path / "repo").resolve(),
        repository_id="control:repo",
        head_sha="abc123",
        is_dirty=False,
        snapshot_id="abc123",
        dirty_fingerprint=None,
    )

    monkeypatch.setattr(
        "taskplane.contextweaver_indexing.resolve_repository_identity",
        lambda project_dir, explicit_repo=None: identity,
    )
    monkeypatch.setattr(
        "taskplane.contextweaver_indexing._run_contextweaver_index",
        lambda project_dir: calls.append(project_dir) or None,
    )
    monkeypatch.setenv("TASKPLANE_CONTEXTWEAVER_LOCK_STALE_SECONDS", "10")
    monkeypatch.setenv("TASKPLANE_CONTEXTWEAVER_LOCK_WAIT_SECONDS", "0.03")
    monkeypatch.setenv("TASKPLANE_CONTEXTWEAVER_LOCK_POLL_SECONDS", "0.01")

    lock_path = registry.lock_path_for_artifact(
        repository_id="control:repo",
        snapshot_id="abc123",
        schema_version="v1",
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("held", encoding="utf-8")

    result = ensure_contextweaver_index_for_checkout(
        tmp_path / "fresh-checkout",
        explicit_repo="repo",
        registry=registry,
    )

    assert result == "timed out waiting for contextweaver snapshot build lock"
    assert calls == []


def test_snapshot_observation_reports_artifact_and_lock_metadata(tmp_path):
    registry = FileIndexRegistry(tmp_path / "registry.json")
    registry.upsert_artifact(
        IndexArtifactRecord(
            repository_id="control:repo",
            snapshot_id="abc123",
            repo_root=str((tmp_path / "repo").resolve()),
            schema_version="v1",
            status="building",
        )
    )
    lock_path = registry.lock_path_for_artifact(
        repository_id="control:repo",
        snapshot_id="abc123",
        schema_version="v1",
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("held", encoding="utf-8")

    observation = registry.inspect_snapshot(
        repository_id="control:repo",
        snapshot_id="abc123",
        schema_version="v1",
    )

    assert isinstance(observation, SnapshotObservation)
    assert observation.artifact is not None
    assert observation.artifact.status == "building"
    assert observation.artifact_age_seconds is not None
    assert observation.lock_path == lock_path
    assert observation.lock_exists is True
    assert observation.lock_age_seconds is not None
    assert observation.lock_is_stale is False


def test_snapshot_observation_reports_stale_lock(tmp_path, monkeypatch):
    registry = FileIndexRegistry(tmp_path / "registry.json")
    monkeypatch.setenv("TASKPLANE_CONTEXTWEAVER_LOCK_STALE_SECONDS", "0.01")
    lock_path = registry.lock_path_for_artifact(
        repository_id="control:repo",
        snapshot_id="abc123",
        schema_version="v1",
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("held", encoding="utf-8")
    stale_time = time.time() - 5
    os.utime(lock_path, (stale_time, stale_time))

    observation = registry.inspect_snapshot(
        repository_id="control:repo",
        snapshot_id="abc123",
        schema_version="v1",
    )

    assert observation.artifact is None
    assert observation.lock_exists is True
    assert observation.lock_is_stale is True
    assert observation.lock_age_seconds is not None
