from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any


SCHEMA_VERSION = "v1"


@dataclass(frozen=True)
class RepositoryIdentity:
    project_dir: Path
    repo_root: Path
    repository_id: str
    head_sha: str
    is_dirty: bool
    snapshot_id: str
    dirty_fingerprint: str | None = None


@dataclass(frozen=True)
class IndexArtifactRecord:
    repository_id: str
    snapshot_id: str
    repo_root: str
    schema_version: str
    status: str
    artifact_path: str | None = None
    last_error: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class CheckoutAliasRecord:
    checkout_path: str
    repository_id: str
    snapshot_id: str
    repo_root: str


@dataclass(frozen=True)
class SnapshotObservation:
    repository_id: str
    snapshot_id: str
    schema_version: str
    artifact: IndexArtifactRecord | None
    artifact_age_seconds: float | None
    lock_path: Path
    lock_exists: bool
    lock_age_seconds: float | None
    lock_is_stale: bool


class FileIndexRegistry:
    def __init__(self, path: Path) -> None:
        self._path = path

    def record_checkout_alias(self, alias: CheckoutAliasRecord) -> None:
        payload = self._load()
        payload["checkout_aliases"][alias.checkout_path] = asdict(alias)
        self._store(payload)

    def get_artifact(
        self,
        *,
        repository_id: str,
        snapshot_id: str,
        schema_version: str,
    ) -> IndexArtifactRecord | None:
        payload = self._load()
        key = self._artifact_key(
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            schema_version=schema_version,
        )
        raw = payload["artifacts"].get(key)
        if not isinstance(raw, dict):
            return None
        return IndexArtifactRecord(**raw)

    def upsert_artifact(self, artifact: IndexArtifactRecord) -> None:
        payload = self._load()
        key = self._artifact_key(
            repository_id=artifact.repository_id,
            snapshot_id=artifact.snapshot_id,
            schema_version=artifact.schema_version,
        )
        artifact_payload = asdict(artifact)
        artifact_payload["updated_at"] = datetime.now(UTC).isoformat()
        payload["artifacts"][key] = artifact_payload
        self._store(payload)

    def lock_path_for_artifact(
        self,
        *,
        repository_id: str,
        snapshot_id: str,
        schema_version: str,
    ) -> Path:
        key = self._artifact_key(
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            schema_version=schema_version,
        )
        return (
            self._path.parent
            / ".locks"
            / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.lock"
        )

    def try_acquire_build_lock(
        self,
        *,
        repository_id: str,
        snapshot_id: str,
        schema_version: str,
    ) -> Path | None:
        lock_path = self.lock_path_for_artifact(
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            schema_version=schema_version,
        )
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        return self._acquire_or_reclaim_lock(lock_path)

    def release_build_lock(self, lock_path: Path | None) -> None:
        if lock_path is None:
            return
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass

    def inspect_snapshot(
        self,
        *,
        repository_id: str,
        snapshot_id: str,
        schema_version: str,
    ) -> SnapshotObservation:
        artifact = self.get_artifact(
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            schema_version=schema_version,
        )
        lock_path = self.lock_path_for_artifact(
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            schema_version=schema_version,
        )
        artifact_age_seconds = self._artifact_age_seconds(
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            schema_version=schema_version,
        )
        lock_age_seconds = self._lock_age_seconds(lock_path)
        return SnapshotObservation(
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            schema_version=schema_version,
            artifact=artifact,
            artifact_age_seconds=artifact_age_seconds,
            lock_path=lock_path,
            lock_exists=lock_path.exists(),
            lock_age_seconds=lock_age_seconds,
            lock_is_stale=self._is_stale_lock(lock_path),
        )

    def list_snapshot_keys(self) -> list[tuple[str, str, str]]:
        payload = self._load()
        keys: list[tuple[str, str, str]] = []
        for raw_key in payload["artifacts"].keys():
            if not isinstance(raw_key, str):
                continue
            repository_id, snapshot_id, schema_version = raw_key.split("::", 2)
            keys.append((repository_id, snapshot_id, schema_version))
        return keys

    def list_checkout_paths_for_snapshot(
        self,
        *,
        repository_id: str,
        snapshot_id: str,
    ) -> list[str]:
        payload = self._load()
        checkout_paths: list[str] = []
        for checkout_path, raw in payload["checkout_aliases"].items():
            if not isinstance(raw, dict):
                continue
            if raw.get("repository_id") != repository_id:
                continue
            if raw.get("snapshot_id") != snapshot_id:
                continue
            checkout_paths.append(str(checkout_path))
        return sorted(checkout_paths)

    def wait_for_artifact_state(
        self,
        *,
        repository_id: str,
        snapshot_id: str,
        schema_version: str,
        timeout_seconds: float,
        poll_seconds: float,
    ) -> IndexArtifactRecord | None:
        deadline = time.monotonic() + max(timeout_seconds, 0.0)
        sleep_seconds = max(poll_seconds, 0.001)
        lock_path = self.lock_path_for_artifact(
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            schema_version=schema_version,
        )
        while True:
            artifact = self.get_artifact(
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                schema_version=schema_version,
            )
            if artifact is not None and artifact.status in {"ready", "failed"}:
                return artifact
            if not lock_path.exists():
                return artifact
            if self._is_stale_lock(lock_path):
                return artifact
            if time.monotonic() >= deadline:
                return None
            time.sleep(sleep_seconds)

    def _acquire_or_reclaim_lock(self, lock_path: Path) -> Path | None:
        try:
            return self._create_lock_file(lock_path)
        except FileExistsError:
            if not self._is_stale_lock(lock_path):
                return None
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
            try:
                return self._create_lock_file(lock_path)
            except FileExistsError:
                return None

    def _create_lock_file(self, lock_path: Path) -> Path:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, str(time.time()).encode("utf-8"))
        finally:
            os.close(fd)
        return lock_path

    def _is_stale_lock(self, lock_path: Path) -> bool:
        try:
            modified_at = lock_path.stat().st_mtime
        except FileNotFoundError:
            return False
        return (time.time() - modified_at) >= _load_lock_stale_seconds()

    def mark_building(self, identity: RepositoryIdentity) -> None:
        self.upsert_artifact(
            IndexArtifactRecord(
                repository_id=identity.repository_id,
                snapshot_id=identity.snapshot_id,
                repo_root=str(identity.repo_root),
                schema_version=SCHEMA_VERSION,
                status="building",
            )
        )

    def mark_ready(self, identity: RepositoryIdentity) -> None:
        self.upsert_artifact(
            IndexArtifactRecord(
                repository_id=identity.repository_id,
                snapshot_id=identity.snapshot_id,
                repo_root=str(identity.repo_root),
                schema_version=SCHEMA_VERSION,
                status="ready",
            )
        )

    def mark_failed(self, identity: RepositoryIdentity, error: str) -> None:
        self.upsert_artifact(
            IndexArtifactRecord(
                repository_id=identity.repository_id,
                snapshot_id=identity.snapshot_id,
                repo_root=str(identity.repo_root),
                schema_version=SCHEMA_VERSION,
                status="failed",
                last_error=error,
            )
        )

    def _artifact_key(
        self,
        *,
        repository_id: str,
        snapshot_id: str,
        schema_version: str,
    ) -> str:
        return f"{repository_id}::{snapshot_id}::{schema_version}"

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"artifacts": {}, "checkout_aliases": {}, "updated_at": None}
        return json.loads(self._path.read_text(encoding="utf-8"))

    def _artifact_age_seconds(
        self,
        *,
        repository_id: str,
        snapshot_id: str,
        schema_version: str,
    ) -> float | None:
        payload = self._load()
        key = self._artifact_key(
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            schema_version=schema_version,
        )
        raw = payload["artifacts"].get(key)
        if not isinstance(raw, dict):
            return None
        updated_at_raw = raw.get("updated_at")
        if not isinstance(updated_at_raw, str) or not updated_at_raw.strip():
            return None
        try:
            updated_at = datetime.fromisoformat(updated_at_raw)
        except ValueError:
            return None
        return max((datetime.now(UTC) - updated_at).total_seconds(), 0.0)

    def _lock_age_seconds(self, lock_path: Path) -> float | None:
        try:
            modified_at = lock_path.stat().st_mtime
        except FileNotFoundError:
            return None
        return max(time.time() - modified_at, 0.0)

    def _store(self, payload: dict[str, Any]) -> None:
        payload["updated_at"] = datetime.now(UTC).isoformat()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def ensure_contextweaver_index_for_checkout(
    project_dir: Path,
    *,
    explicit_repo: str | None = None,
    registry: FileIndexRegistry | None = None,
) -> str | None:
    if _skip_indexing_enabled():
        return None
    identity = resolve_repository_identity(project_dir, explicit_repo=explicit_repo)
    registry = registry or FileIndexRegistry(_default_registry_path())
    registry.record_checkout_alias(
        CheckoutAliasRecord(
            checkout_path=str(identity.project_dir),
            repository_id=identity.repository_id,
            snapshot_id=identity.snapshot_id,
            repo_root=str(identity.repo_root),
        )
    )
    existing = registry.get_artifact(
        repository_id=identity.repository_id,
        snapshot_id=identity.snapshot_id,
        schema_version=SCHEMA_VERSION,
    )
    if existing is not None and existing.status == "ready":
        return None
    lock_path = registry.try_acquire_build_lock(
        repository_id=identity.repository_id,
        snapshot_id=identity.snapshot_id,
        schema_version=SCHEMA_VERSION,
    )
    if lock_path is None:
        observed = registry.wait_for_artifact_state(
            repository_id=identity.repository_id,
            snapshot_id=identity.snapshot_id,
            schema_version=SCHEMA_VERSION,
            timeout_seconds=_load_lock_wait_seconds(),
            poll_seconds=_load_lock_poll_seconds(),
        )
        if observed is not None and observed.status == "ready":
            return None
        if observed is not None and observed.status == "failed":
            return observed.last_error or "contextweaver index failed"
        return "timed out waiting for contextweaver snapshot build lock"
    try:
        existing = registry.get_artifact(
            repository_id=identity.repository_id,
            snapshot_id=identity.snapshot_id,
            schema_version=SCHEMA_VERSION,
        )
        if existing is not None and existing.status == "ready":
            return None
        registry.mark_building(identity)
        error = _run_contextweaver_index(identity.project_dir)
        if error is None:
            registry.mark_ready(identity)
        else:
            registry.mark_failed(identity, error)
        return error
    finally:
        registry.release_build_lock(lock_path)


def resolve_repository_identity(
    project_dir: Path,
    *,
    explicit_repo: str | None = None,
) -> RepositoryIdentity:
    resolved_project_dir = project_dir.resolve()
    repo_root = _resolve_git_root(resolved_project_dir)
    if repo_root is None:
        raise RuntimeError(f"unable to resolve git repository root from {project_dir}")
    head_sha = _git_stdout(repo_root, ["rev-parse", "HEAD"]).strip()
    is_dirty = bool(_git_stdout(repo_root, ["status", "--porcelain"]).strip())
    repository_id = _derive_repository_id(
        explicit_repo=explicit_repo,
        repo_root=repo_root,
    )
    dirty_fingerprint = None
    snapshot_id = head_sha
    if is_dirty:
        dirty_fingerprint = _compute_dirty_snapshot_fingerprint(repo_root)
        snapshot_id = f"{head_sha}:dirty:{dirty_fingerprint}"
    return RepositoryIdentity(
        project_dir=resolved_project_dir,
        repo_root=repo_root,
        repository_id=repository_id,
        head_sha=head_sha,
        is_dirty=is_dirty,
        snapshot_id=snapshot_id,
        dirty_fingerprint=dirty_fingerprint,
    )


def _default_registry_path() -> Path:
    override = os.environ.get("STARDRIFTER_CONTEXTWEAVER_REGISTRY_PATH", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".cache" / "contextweaver" / "registry.json"


def _skip_indexing_enabled() -> bool:
    return os.environ.get(
        "STARDRIFTER_SKIP_CONTEXTWEAVER_INDEX", ""
    ).strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _load_lock_wait_seconds() -> float:
    raw = os.environ.get("STARDRIFTER_CONTEXTWEAVER_LOCK_WAIT_SECONDS", "5").strip()
    try:
        value = float(raw)
    except ValueError:
        return 5.0
    if value < 0:
        return 5.0
    return value


def _load_lock_poll_seconds() -> float:
    raw = os.environ.get("STARDRIFTER_CONTEXTWEAVER_LOCK_POLL_SECONDS", "0.05").strip()
    try:
        value = float(raw)
    except ValueError:
        return 0.05
    if value <= 0:
        return 0.05
    return value


def _load_lock_stale_seconds() -> float:
    raw = os.environ.get("STARDRIFTER_CONTEXTWEAVER_LOCK_STALE_SECONDS", "30").strip()
    try:
        value = float(raw)
    except ValueError:
        return 30.0
    if value < 0:
        return 30.0
    return value


def _derive_repository_id(*, explicit_repo: str | None, repo_root: Path) -> str:
    if explicit_repo and explicit_repo.strip():
        return f"control:{explicit_repo.strip()}"
    remote = _try_git_stdout(repo_root, ["remote", "get-url", "origin"])
    if remote:
        normalized = _normalize_remote_url(remote.strip())
        if normalized:
            return f"git:{normalized}"
    return f"local:{repo_root.resolve()}"


def _normalize_remote_url(remote: str) -> str:
    normalized = remote.strip()
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    if normalized.startswith("git@") and ":" in normalized:
        host_part, path_part = normalized.split(":", 1)
        return f"{host_part[4:]}/{path_part}"
    if normalized.startswith("https://"):
        return normalized[len("https://") :]
    if normalized.startswith("http://"):
        return normalized[len("http://") :]
    return normalized


def _resolve_git_root(project_dir: Path) -> Path | None:
    completed = subprocess.run(
        ["git", "-C", str(project_dir), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    output = (completed.stdout or "").strip()
    if not output:
        return None
    return Path(output).resolve()


def _git_stdout(repo_root: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        raise RuntimeError(stderr or f"git command failed: {' '.join(args)}")
    return completed.stdout or ""


def _try_git_stdout(repo_root: Path, args: list[str]) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return (completed.stdout or "").strip() or None


def _compute_dirty_snapshot_fingerprint(repo_root: Path) -> str:
    status_output = _git_stdout(repo_root, ["status", "--porcelain"])
    diff_output = _git_stdout(repo_root, ["diff", "--no-ext-diff", "--binary", "HEAD"])
    digest = hashlib.sha256()
    digest.update(status_output.encode("utf-8"))
    digest.update(b"\0")
    digest.update(diff_output.encode("utf-8"))
    return digest.hexdigest()[:16]


def _run_contextweaver_index(project_dir: Path) -> str | None:
    completed = subprocess.run(
        ["contextweaver", "index", str(project_dir)],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        return None
    stderr = (completed.stderr or "").strip()
    stdout = (completed.stdout or "").strip()
    return stderr or stdout or f"exit={completed.returncode}"
