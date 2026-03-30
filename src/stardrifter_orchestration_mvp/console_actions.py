from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shlex
from types import SimpleNamespace
from typing import Any, Callable

from .factory import build_postgres_repository
from .scheduling_loop import _load_running_jobs
from .supervisor_cli import _launch_managed_process
from .job_launcher import insert_execution_job as _insert_execution_job


def _build_decomposition_command(*, dsn, repo, story_issue_number, project_dir):
    """Build story decomposition command."""
    cmd = f"python3 -m stardrifter_orchestration_mvp.opencode_story_decomposer --repo {repo} --story {story_issue_number}"
    return f"STARDRIFTER_ORCHESTRATION_DSN={dsn} cd {project_dir} && {cmd}"


def _build_epic_decomposition_command(*, dsn, repo, epic_issue_number, project_dir):
    """Build epic decomposition command."""
    cmd = f"python3 -m stardrifter_orchestration_mvp.opencode_epic_decomposer --repo {repo} --epic {epic_issue_number}"
    return f"STARDRIFTER_ORCHESTRATION_DSN={dsn} cd {project_dir} && {cmd}"


DEFAULT_EPIC_DECOMPOSER_COMMAND = (
    "python3 -m stardrifter_orchestration_mvp.opencode_epic_decomposer"
)
DEFAULT_STORY_DECOMPOSER_COMMAND = (
    "python3 -m stardrifter_orchestration_mvp.opencode_story_decomposer"
)


@dataclass(frozen=True)
class ConsoleActionSettings:
    dsn: str
    repo_workdirs: dict[str, str]
    repo_log_dirs: dict[str, str]
    epic_decomposer_command: str = DEFAULT_EPIC_DECOMPOSER_COMMAND
    story_decomposer_command: str = DEFAULT_STORY_DECOMPOSER_COMMAND


class ConsoleActionConfigurationError(RuntimeError):
    pass


class ConsoleActionConflictError(RuntimeError):
    pass


class ConsoleActionNotFoundError(RuntimeError):
    pass


def load_console_action_settings_from_env() -> ConsoleActionSettings:
    dsn = os.getenv("STARDRIFTER_ORCHESTRATION_DSN", "").strip()
    if not dsn:
        raise ConsoleActionConfigurationError(
            "STARDRIFTER_ORCHESTRATION_DSN is required"
        )

    raw_mapping = os.getenv("STARDRIFTER_CONSOLE_REPO_WORKDIRS_JSON", "").strip()
    if not raw_mapping:
        raise ConsoleActionConfigurationError(
            "STARDRIFTER_CONSOLE_REPO_WORKDIRS_JSON is required"
        )
    try:
        parsed = json.loads(raw_mapping)
    except json.JSONDecodeError as exc:
        raise ConsoleActionConfigurationError(
            "STARDRIFTER_CONSOLE_REPO_WORKDIRS_JSON must be valid JSON"
        ) from exc
    if not isinstance(parsed, dict):
        raise ConsoleActionConfigurationError(
            "STARDRIFTER_CONSOLE_REPO_WORKDIRS_JSON must be a JSON object"
        )

    raw_log_mapping = os.getenv("STARDRIFTER_CONSOLE_REPO_LOG_DIRS_JSON", "").strip()
    if not raw_log_mapping:
        raise ConsoleActionConfigurationError(
            "STARDRIFTER_CONSOLE_REPO_LOG_DIRS_JSON is required"
        )
    try:
        parsed_logs = json.loads(raw_log_mapping)
    except json.JSONDecodeError as exc:
        raise ConsoleActionConfigurationError(
            "STARDRIFTER_CONSOLE_REPO_LOG_DIRS_JSON must be valid JSON"
        ) from exc
    if not isinstance(parsed_logs, dict):
        raise ConsoleActionConfigurationError(
            "STARDRIFTER_CONSOLE_REPO_LOG_DIRS_JSON must be a JSON object"
        )

    repo_workdirs: dict[str, str] = {}
    for repo, workdir in parsed.items():
        repo_name = str(repo).strip()
        workdir_value = str(workdir).strip()
        if repo_name and workdir_value:
            repo_workdirs[repo_name] = workdir_value

    if not repo_workdirs:
        raise ConsoleActionConfigurationError(
            "STARDRIFTER_CONSOLE_REPO_WORKDIRS_JSON must define at least one repo"
        )

    repo_log_dirs: dict[str, str] = {}
    for repo, log_dir in parsed_logs.items():
        repo_name = str(repo).strip()
        log_dir_value = str(log_dir).strip()
        if repo_name and log_dir_value:
            repo_log_dirs[repo_name] = log_dir_value

    if not repo_log_dirs:
        raise ConsoleActionConfigurationError(
            "STARDRIFTER_CONSOLE_REPO_LOG_DIRS_JSON must define at least one repo"
        )

    return ConsoleActionSettings(
        dsn=dsn,
        repo_workdirs=repo_workdirs,
        repo_log_dirs=repo_log_dirs,
        epic_decomposer_command=(
            os.getenv(
                "STARDRIFTER_CONSOLE_EPIC_DECOMPOSER_COMMAND",
                DEFAULT_EPIC_DECOMPOSER_COMMAND,
            ).strip()
            or DEFAULT_EPIC_DECOMPOSER_COMMAND
        ),
        story_decomposer_command=(
            os.getenv(
                "STARDRIFTER_CONSOLE_STORY_DECOMPOSER_COMMAND",
                DEFAULT_STORY_DECOMPOSER_COMMAND,
            ).strip()
            or DEFAULT_STORY_DECOMPOSER_COMMAND
        ),
    )


def run_epic_split_action(
    *,
    repo: str,
    epic_issue_number: int,
    settings: ConsoleActionSettings | None = None,
    repository_builder: Callable[..., Any] = build_postgres_repository,
    epic_command_builder: Callable[..., str] = _build_epic_decomposition_command,
    process_launcher: Callable[..., Any] = _launch_managed_process,
    job_inserter: Callable[..., Any] = _insert_execution_job,
    running_job_loader: Callable[..., list[dict[str, Any]]] = _load_running_jobs,
) -> dict[str, Any]:
    settings = settings or load_console_action_settings_from_env()
    workdir = _resolve_workdir(settings=settings, repo=repo)
    log_dir = _resolve_log_dir(settings=settings, repo=repo)
    repository = repository_builder(dsn=settings.dsn)
    connection = getattr(repository, "_connection", None)
    _ensure_epic_can_split(
        repository=repository,
        repo=repo,
        epic_issue_number=epic_issue_number,
        running_jobs=(
            running_job_loader(connection=connection, repo=repo)
            if connection is not None
            else []
        ),
    )
    command = epic_command_builder(
        dsn=settings.dsn,
        repo=repo,
        epic_issue_number=epic_issue_number,
        project_dir=workdir,
    )
    command = _override_decomposer_command(
        command=command,
        expected_default=DEFAULT_EPIC_DECOMPOSER_COMMAND,
        configured_command=settings.epic_decomposer_command,
    )
    log_path = log_dir / f"epic-{epic_issue_number}-decomposition.log"
    process = process_launcher(command, log_path)
    if connection is not None:
        job_inserter(
            connection=connection,
            repo=repo,
            job_kind="epic_decomposition",
            story_issue_number=epic_issue_number,
            work_id=None,
            launch_backend="console",
            worker_name=f"console-epic-{epic_issue_number}",
            pid=process.pid,
            command=command,
            log_path=str(log_path),
        )
    return {
        "accepted": True,
        "action": "split_epic",
        "repo": repo,
        "epic_issue_number": epic_issue_number,
        "workdir": str(workdir),
        "job": {
            "job_kind": "epic_decomposition",
            "pid": process.pid,
            "worker_name": f"console-epic-{epic_issue_number}",
            "command": command,
            "log_path": str(log_path),
            "launch_backend": "console",
        },
    }


def run_story_split_action(
    *,
    repo: str,
    story_issue_number: int,
    settings: ConsoleActionSettings | None = None,
    repository_builder: Callable[..., Any] = build_postgres_repository,
    story_command_builder: Callable[..., str] = _build_decomposition_command,
    process_launcher: Callable[..., Any] = _launch_managed_process,
    job_inserter: Callable[..., Any] = _insert_execution_job,
    running_job_loader: Callable[..., list[dict[str, Any]]] = _load_running_jobs,
) -> dict[str, Any]:
    settings = settings or load_console_action_settings_from_env()
    workdir = _resolve_workdir(settings=settings, repo=repo)
    log_dir = _resolve_log_dir(settings=settings, repo=repo)
    repository = repository_builder(dsn=settings.dsn)
    connection = getattr(repository, "_connection", None)
    _ensure_story_can_split(
        repository=repository,
        repo=repo,
        story_issue_number=story_issue_number,
        running_jobs=(
            running_job_loader(connection=connection, repo=repo)
            if connection is not None
            else []
        ),
    )
    command = story_command_builder(
        dsn=settings.dsn,
        repo=repo,
        story_issue_number=story_issue_number,
        project_dir=workdir,
    )
    command = _override_decomposer_command(
        command=command,
        expected_default=DEFAULT_STORY_DECOMPOSER_COMMAND,
        configured_command=settings.story_decomposer_command,
    )
    log_path = log_dir / f"story-{story_issue_number}-decomposition.log"
    process = process_launcher(command, log_path)
    if connection is not None:
        job_inserter(
            connection=connection,
            repo=repo,
            job_kind="story_decomposition",
            story_issue_number=story_issue_number,
            work_id=None,
            launch_backend="console",
            worker_name=f"console-story-{story_issue_number}",
            pid=process.pid,
            command=command,
            log_path=str(log_path),
        )
    return {
        "accepted": True,
        "action": "split_story",
        "repo": repo,
        "story_issue_number": story_issue_number,
        "workdir": str(workdir),
        "job": {
            "job_kind": "story_decomposition",
            "pid": process.pid,
            "worker_name": f"console-story-{story_issue_number}",
            "command": command,
            "log_path": str(log_path),
            "launch_backend": "console",
        },
    }


def run_task_retry_action(
    *,
    repo: str,
    work_id: str,
    repository: Any | None = None,
    settings: ConsoleActionSettings | None = None,
    repository_builder: Callable[..., Any] = build_postgres_repository,
) -> dict[str, Any]:
    if repository is None:
        settings = settings or load_console_action_settings_from_env()
        repository = repository_builder(dsn=settings.dsn)
    if repository is None:
        raise ConsoleActionConfigurationError(
            "Repository builder returned no repository"
        )

    work_item = repository.get_work_item(work_id)
    if work_item.repo not in {None, repo}:
        raise ConsoleActionConflictError(
            f"task {work_id} belongs to repo {work_item.repo}, not {repo}"
        )
    if work_item.status in {"in_progress", "verifying", "done"}:
        raise ConsoleActionConflictError(
            f"task {work_id} cannot be retried from status {work_item.status}"
        )

    active_claim = next(
        (
            claim
            for claim in repository.list_active_work_claims()
            if claim.work_id == work_id
        ),
        None,
    )
    if active_claim is not None and work_item.status in {"in_progress", "verifying"}:
        raise ConsoleActionConflictError(f"task {work_id} is already running")

    if active_claim is not None:
        repository.delete_work_claim(work_id)

    previous_status = work_item.status
    repository.update_work_status(
        work_id,
        "pending",
        blocked_reason=None,
        decision_required=False,
        attempt_count=work_item.attempt_count,
        last_failure_reason=work_item.last_failure_reason,
        next_eligible_at=None,
    )
    repository.sync_ready_states()
    refreshed = repository.get_work_item(work_id)

    return {
        "accepted": True,
        "action": "retry_task",
        "repo": repo,
        "work_id": work_id,
        "previous_status": previous_status,
        "new_status": refreshed.status,
        "retry_context": {
            "attempt_count": refreshed.attempt_count,
            "last_failure_reason": refreshed.last_failure_reason,
            "next_eligible_at": refreshed.next_eligible_at,
            "blocked_reason": refreshed.blocked_reason,
            "decision_required": refreshed.decision_required,
        },
    }


def _resolve_workdir(*, settings: ConsoleActionSettings, repo: str) -> Path:
    raw_workdir = settings.repo_workdirs.get(repo, "").strip()
    if not raw_workdir:
        raise ConsoleActionConfigurationError(f"No configured workdir for repo {repo}")
    workdir = Path(raw_workdir).expanduser().resolve()
    if not workdir.exists() or not workdir.is_dir():
        raise ConsoleActionConfigurationError(
            f"Configured workdir does not exist for repo {repo}: {workdir}"
        )
    return workdir


def _resolve_log_dir(*, settings: ConsoleActionSettings, repo: str) -> Path:
    raw_log_dir = settings.repo_log_dirs.get(repo, "").strip()
    if not raw_log_dir:
        raise ConsoleActionConfigurationError(f"No configured log dir for repo {repo}")
    log_dir = Path(raw_log_dir).expanduser().resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    if not log_dir.is_dir():
        raise ConsoleActionConfigurationError(
            f"Configured log dir is not a directory for repo {repo}: {log_dir}"
        )
    return log_dir


def _normalize_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if hasattr(result, "__dataclass_fields__"):
        return asdict(result)
    return {"value": str(result)}


def _ensure_epic_can_split(
    *,
    repository: Any,
    repo: str,
    epic_issue_number: int,
    running_jobs: list[dict[str, Any]],
) -> None:
    loader = getattr(repository, "get_program_epic", None)
    if not callable(loader):
        return
    epic = loader(repo=repo, issue_number=epic_issue_number)
    if epic is None:
        raise ConsoleActionNotFoundError(
            f"epic #{epic_issue_number} not found in {repo}"
        )
    status = str(_get_mapping_value(epic, "execution_status") or "")
    if status in {"decomposing", "active", "done"}:
        raise ConsoleActionConflictError(
            f"epic #{epic_issue_number} cannot be split from status {status}"
        )
    if any(
        str(row.get("job_kind") or "") == "epic_decomposition"
        and row.get("story_issue_number") == epic_issue_number
        and str(row.get("status") or "") == "running"
        for row in running_jobs
    ):
        raise ConsoleActionConflictError(
            f"epic #{epic_issue_number} already has a running decomposition job"
        )


def _ensure_story_can_split(
    *,
    repository: Any,
    repo: str,
    story_issue_number: int,
    running_jobs: list[dict[str, Any]],
) -> None:
    loader = getattr(repository, "get_program_story", None)
    if not callable(loader):
        return
    story = loader(repo=repo, issue_number=story_issue_number)
    if story is None:
        raise ConsoleActionNotFoundError(
            f"story #{story_issue_number} not found in {repo}"
        )
    status = str(_get_mapping_value(story, "execution_status") or "")
    task_count = int(_get_mapping_value(story, "task_count") or 0)
    if status == "decomposing":
        raise ConsoleActionConflictError(
            f"story #{story_issue_number} is already decomposing"
        )
    if any(
        str(row.get("job_kind") or "") == "story_decomposition"
        and row.get("story_issue_number") == story_issue_number
        and str(row.get("status") or "") == "running"
        for row in running_jobs
    ):
        raise ConsoleActionConflictError(
            f"story #{story_issue_number} already has a running decomposition job"
        )
    if status in {"active", "done"} and task_count > 0:
        raise ConsoleActionConflictError(
            f"story #{story_issue_number} already has projected tasks"
        )


def _get_mapping_value(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def _override_decomposer_command(
    *, command: str, expected_default: str, configured_command: str
) -> str:
    configured = configured_command.strip()
    expected = expected_default.strip()
    if not configured or configured == expected or expected not in command:
        return command
    return command.replace(expected, shlex.quote(configured), 1)
