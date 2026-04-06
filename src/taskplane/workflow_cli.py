from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
import subprocess
from typing import Any, cast

from .console_actions import run_operator_request_ack_action
from .console_api import get_repo_summary, list_running_jobs
from .factory import build_postgres_repository
from .intake_api_routes import list_natural_language_intents
from .intake_cli import _print_intent
from .intake_service import (
    IntakeAnalyzer,
    NaturalLanguageIntakeService,
    build_default_analyzer,
)
from .repository import ControlPlaneRepository
from .orchestrator_session_service import (
    handle_orchestrator_session_action,
    start_orchestrator_session,
    watch_orchestrator_session,
)
from .settings import TaskplaneConfig, load_taskplane_config


def main(
    argv: Sequence[str] | None = None,
    *,
    config_loader: Callable[[], TaskplaneConfig] = load_taskplane_config,
    connector: Callable[[str], Any] | None = None,
    repository_builder: Callable[..., object] = build_postgres_repository,
    analyzer_builder: Callable[..., object] = build_default_analyzer,
    repo_locator: Callable[[Path], str] | None = None,
    register_repo: Callable[..., bool] | None = None,
    intake_service_builder: Callable[[], Any] | None = None,
    status_loader: Callable[[str], dict[str, Any]] | None = None,
    orchestrator_start: Callable[..., Any] = start_orchestrator_session,
    orchestrator_watch: Callable[..., Any] = watch_orchestrator_session,
    orchestrator_handle: Callable[..., Any] = handle_orchestrator_session_action,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    config = config_loader()

    if args.command == "link":
        return _run_link(
            args=args,
            config=config,
            connector=connector or _default_connector,
            repo_locator=repo_locator or _detect_repo_from_git,
            register_repo=register_repo or _register_repo,
        )

    if args.command == "intake":
        return _run_intake(
            args=args,
            config=config,
            repo_locator=repo_locator or _detect_repo_from_git,
            intake_service_builder=intake_service_builder
            or (
                lambda: _build_intake_service(
                    repository_builder=repository_builder,
                    analyzer_builder=analyzer_builder,
                    dsn=_require_dsn(config),
                )
            ),
        )

    if args.command == "status":
        return _run_status(
            args=args,
            config=config,
            repo_locator=repo_locator or _detect_repo_from_git,
            status_loader=status_loader
            or (lambda repo: _load_status(repo=repo, dsn=_require_dsn(config))),
        )

    if args.command == "start":
        repository = cast(
            ControlPlaneRepository, repository_builder(dsn=_require_dsn(config))
        )
        return _run_start(
            args=args,
            config=config,
            repo_locator=repo_locator or _detect_repo_from_git,
            repository=repository,
            start_fn=orchestrator_start,
        )

    if args.command == "watch":
        repository = cast(
            ControlPlaneRepository, repository_builder(dsn=_require_dsn(config))
        )
        return _run_watch(
            args=args,
            repository=repository,
            watch_fn=orchestrator_watch,
        )

    if args.command == "handle":
        repository = cast(
            ControlPlaneRepository, repository_builder(dsn=_require_dsn(config))
        )
        return _run_handle(
            args=args,
            repository=repository,
            handle_fn=orchestrator_handle,
            intake_service_builder=intake_service_builder
            or (
                lambda: _build_intake_service(
                    repository_builder=repository_builder,
                    analyzer_builder=analyzer_builder,
                    dsn=_require_dsn(config),
                )
            ),
        )

    parser.error("unsupported command")
    return 2


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taskplane-workflow",
        description="High-level Taskplane workflow commands for link/intake/status.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    link = subparsers.add_parser("link")
    link.add_argument("--repo")
    link.add_argument("--workdir")
    link.add_argument("--log-dir")

    intake = subparsers.add_parser("intake")
    intake.add_argument("prompt", nargs="?")
    intake.add_argument("--repo")
    intake.add_argument("--intent")
    intake_group = intake.add_mutually_exclusive_group()
    intake_group.add_argument("--answer")
    intake_group.add_argument("--approve", action="store_true")
    intake_group.add_argument("--reject")
    intake_group.add_argument("--revise")
    intake_group.add_argument("--request")
    intake.add_argument("--approver", default="operator")
    intake.add_argument("--reviewer", default="operator")

    status = subparsers.add_parser("status")
    status.add_argument("--repo")

    start = subparsers.add_parser("start")
    start.add_argument("--repo")
    start.add_argument("--story", type=int)
    start.add_argument("--host-tool", default="unknown")
    start.add_argument("--started-by", default="operator")

    watch = subparsers.add_parser("watch")
    watch.add_argument("--session", required=True)

    handle = subparsers.add_parser("handle")
    handle.add_argument("--session", required=True)
    handle.add_argument("--repo")
    handle.add_argument("--request")
    handle.add_argument("--intent")
    handle.add_argument("--answer")
    handle_group = handle.add_mutually_exclusive_group()
    handle_group.add_argument("--approve", action="store_true")
    handle_group.add_argument("--reject")
    handle.add_argument("--revise")

    return parser


def _run_link(
    *,
    args: argparse.Namespace,
    config: TaskplaneConfig,
    connector: Callable[[str], Any],
    repo_locator: Callable[[Path], str],
    register_repo: Callable[..., bool],
) -> int:
    dsn = _require_dsn(config)
    cwd = Path.cwd().resolve()
    repo = str(args.repo or repo_locator(cwd)).strip()
    if not repo:
        raise SystemExit("unable to determine repo; pass --repo owner/repo")
    workdir = Path(args.workdir).expanduser().resolve() if args.workdir else cwd
    log_dir = (
        Path(args.log_dir).expanduser().resolve()
        if args.log_dir
        else (workdir / ".taskplane" / "logs").resolve()
    )
    log_dir.mkdir(parents=True, exist_ok=True)

    connection = connector(dsn)
    try:
        created = register_repo(
            connection,
            repo=repo,
            workdir=workdir,
            log_dir=log_dir,
        )
    finally:
        close = getattr(connection, "close", None)
        if callable(close):
            close()

    _upsert_taskplane_toml(config=config, repo=repo, workdir=workdir, log_dir=log_dir)
    print(f"已链接仓库到 Taskplane: {repo}")
    print(f"- workdir: {workdir}")
    print(f"- log_dir: {log_dir}")
    print(f"- repo registration: {'created' if created else 'updated'}")
    print('下一步: /tp-intake "你的需求"')
    return 0


def _run_intake(
    *,
    args: argparse.Namespace,
    config: TaskplaneConfig,
    repo_locator: Callable[[Path], str],
    intake_service_builder: Callable[[], Any],
) -> int:
    service = intake_service_builder()

    if args.request:
        request_repo, epic_issue_number, reason_code = _parse_request_ref(
            args.request,
            fallback_repo=str(args.repo or repo_locator(Path.cwd().resolve())).strip(),
        )
        payload = run_operator_request_ack_action(
            repo=request_repo,
            epic_issue_number=epic_issue_number,
            reason_code=reason_code,
            closed_reason="approved",
        )
        print(f"已处理 operator request: {args.request}")
        print(payload)
        return 0

    if args.intent:
        if args.answer:
            intent = service.answer_intent(intent_id=args.intent, answer=args.answer)
        elif args.approve:
            intent = service.approve_intent(
                intent_id=args.intent, approver=args.approver
            )
        elif args.reject:
            intent = service.reject_intent(
                intent_id=args.intent,
                reviewer=args.reviewer,
                reason=args.reject,
            )
        elif args.revise:
            intent = service.revise_intent(
                intent_id=args.intent,
                reviewer=args.reviewer,
                feedback=args.revise,
            )
        else:
            raise SystemExit(
                "intent mode requires --answer/--approve/--reject/--revise"
            )
    else:
        repo = str(args.repo or repo_locator(Path.cwd().resolve())).strip()
        if not args.prompt:
            raise SystemExit("submit mode requires a prompt")
        intent = service.submit_intent(repo=repo, prompt=args.prompt)

    _print_intent(intent)
    _print_intake_guidance(intent)
    return 0


def _run_status(
    *,
    args: argparse.Namespace,
    config: TaskplaneConfig,
    repo_locator: Callable[[Path], str],
    status_loader: Callable[[str], dict[str, Any]],
) -> int:
    repo = str(args.repo or repo_locator(Path.cwd().resolve())).strip()
    payload = status_loader(repo)
    _print_status(payload)
    return 0


def _run_start(
    *,
    args: argparse.Namespace,
    config: TaskplaneConfig,
    repo_locator: Callable[[Path], str],
    repository: ControlPlaneRepository,
    start_fn: Callable[..., Any],
) -> int:
    repo = str(args.repo or repo_locator(Path.cwd().resolve())).strip()
    result = start_fn(
        repository=repository,
        repo=repo,
        dsn=_require_dsn(config),
        host_tool=str(args.host_tool or "unknown").strip(),
        started_by=str(args.started_by or "operator").strip(),
        story_issue_number=args.story,
        launch_fn=_default_orchestrator_launch,
    )
    print(f"orchestrator session: {result.session.id}")
    print(f"repo: {result.session.repo}")
    print(f"host tool: {result.session.host_tool}")
    print(f"launched jobs: {len(result.launched_jobs)}")
    if result.watched_story_issue_numbers:
        print(
            f"watched stories: {', '.join(str(v) for v in result.watched_story_issue_numbers)}"
        )
    print(f"next: /tp-watch --session {result.session.id}")
    return 0


def _run_watch(
    *,
    args: argparse.Namespace,
    repository: ControlPlaneRepository,
    watch_fn: Callable[..., Any],
) -> int:
    payload = watch_fn(repository=repository, session_id=args.session)
    session = payload["session"]
    print(f"orchestrator session: {session.id}")
    print(f"repo: {session.repo}")
    print(f"host tool: {session.host_tool}")
    current_phase = payload.get("current_phase")
    if current_phase:
        print(f"current phase: {current_phase}")
    canonical_loop = payload.get("canonical_loop") or []
    if canonical_loop:
        print(f"canonical loop: {' -> '.join(str(value) for value in canonical_loop)}")
    compact_summary = payload.get("compact_summary") or {}
    if compact_summary:
        objective_summary = str(compact_summary.get("objective_summary") or "").strip()
        plan_summary = str(compact_summary.get("plan_summary") or "").strip()
        handoff_summary = str(compact_summary.get("handoff_summary") or "").strip()
        if objective_summary:
            print(f"objective: {objective_summary}")
        if plan_summary:
            print(f"plan summary: {plan_summary}")
        if handoff_summary:
            print(f"handoff summary: {handoff_summary}")
    print(f"jobs: {len(payload.get('jobs') or [])}")
    for job in payload.get("jobs") or []:
        print(
            f"- job #{job.get('id')} {job.get('job_kind')} status={job.get('status')}"
        )
    intents = payload.get("intents") or []
    if intents:
        print(f"pending intents: {len(intents)}")
    for intent in intents:
        print(f"- intent {intent.id} status={intent.status} summary={intent.summary}")
    blocked_tasks = payload.get("blocked_tasks") or []
    if blocked_tasks:
        print(f"blocked tasks: {len(blocked_tasks)}")
    for task in blocked_tasks:
        print(
            f"- blocked task {task.id} title={task.title} reason={task.blocked_reason} decision_required={task.decision_required}"
        )
    for request in payload.get("operator_requests") or []:
        print(
            f"- operator request epic:{request.epic_issue_number}:{request.reason_code}"
        )
    recommended_actions = payload.get("recommended_actions") or []
    if recommended_actions:
        print("recommended next actions:")
    for action in recommended_actions:
        print(f"- {action}")
    return 0


def _run_handle(
    *,
    args: argparse.Namespace,
    repository: ControlPlaneRepository,
    handle_fn: Callable[..., Any],
    intake_service_builder: Callable[[], Any],
) -> int:
    intake_service = intake_service_builder()
    if args.request:
        repo, epic_issue_number, reason_code = _parse_request_ref(
            args.request,
            fallback_repo=str(args.repo or "").strip(),
        )
        action = handle_fn(
            repository=repository,
            session_id=args.session,
            action_type="ack_operator_request",
            payload={
                "repo": repo,
                "epic_issue_number": epic_issue_number,
                "reason_code": reason_code,
                "closed_reason": "approved"
                if args.approve or not args.reject
                else args.reject,
            },
            intake_service=intake_service,
        )
        closed_request = action.get("closed_request")
        print(f"action: {action.get('action')}")
        if closed_request is not None:
            print(
                f"closed operator request epic:{closed_request.epic_issue_number}:{closed_request.reason_code} -> {closed_request.closed_reason}"
            )
        return 0
    if args.intent and args.answer:
        action = handle_fn(
            repository=repository,
            session_id=args.session,
            action_type="answer_intent",
            payload={"intent_id": args.intent, "answer": args.answer},
            intake_service=intake_service,
        )
        intent = action.get("intent")
        print(f"action: {action.get('action')}")
        if intent is not None:
            print(f"intent {intent.id} -> {intent.status}")
        return 0
    if args.intent and args.approve:
        action = handle_fn(
            repository=repository,
            session_id=args.session,
            action_type="approve_intent",
            payload={"intent_id": args.intent, "approver": "operator"},
            intake_service=intake_service,
        )
        intent = action.get("intent")
        print(f"action: {action.get('action')}")
        if intent is not None:
            print(f"intent {intent.id} -> {intent.status}")
        return 0
    if args.intent and args.reject:
        action = handle_fn(
            repository=repository,
            session_id=args.session,
            action_type="reject_intent",
            payload={
                "intent_id": args.intent,
                "reason": args.reject,
                "reviewer": "operator",
            },
            intake_service=intake_service,
        )
        intent = action.get("intent")
        print(f"action: {action.get('action')}")
        if intent is not None:
            print(f"intent {intent.id} -> {intent.status}")
        return 0
    if args.intent and args.revise:
        action = handle_fn(
            repository=repository,
            session_id=args.session,
            action_type="revise_intent",
            payload={
                "intent_id": args.intent,
                "feedback": args.revise,
                "reviewer": "operator",
            },
            intake_service=intake_service,
        )
        intent = action.get("intent")
        print(f"action: {action.get('action')}")
        if intent is not None:
            print(f"intent {intent.id} -> {intent.status}")
        return 0
    raise SystemExit("handle requires --request or an intent action")


def _default_orchestrator_launch(
    *, repo: str, dsn: str, session_id: str, story_issue_number: int | None = None
) -> dict[str, Any]:
    del dsn, session_id
    watched_story_issue_numbers = [story_issue_number] if story_issue_number else []
    return {
        "launched_jobs": [
            {
                "id": 1,
                "job_kind": "story_worker" if story_issue_number else "supervisor",
                "status": "running",
                "story_issue_number": story_issue_number,
                "repo": repo,
            }
        ],
        "watched_story_issue_numbers": watched_story_issue_numbers,
    }


def _require_dsn(config: TaskplaneConfig) -> str:
    dsn = config.postgres_dsn.strip()
    if not dsn:
        raise SystemExit(
            "TASKPLANE_DSN is required (or set [postgres].dsn in taskplane.toml)"
        )
    return dsn


def _build_intake_service(
    *,
    repository_builder: Callable[..., object],
    analyzer_builder: Callable[..., object],
    dsn: str,
) -> NaturalLanguageIntakeService:
    repository_obj = repository_builder(dsn=dsn)
    analyzer_obj = analyzer_builder(repository_obj)
    repository = cast(ControlPlaneRepository, repository_obj)
    analyzer = cast(IntakeAnalyzer, analyzer_obj)
    return NaturalLanguageIntakeService(repository=repository, analyzer=analyzer)


def _default_connector(dsn: str) -> Any:
    import psycopg

    return psycopg.connect(dsn)


def _detect_repo_from_git(cwd: Path) -> str:
    result = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=cwd,
        capture_output=True,
        check=True,
        text=True,
    )
    remote = result.stdout.strip()
    if not remote:
        raise SystemExit("unable to determine repo from git remote.origin.url")
    normalized = remote.removesuffix(".git")
    if normalized.startswith("git@github.com:"):
        return normalized.split(":", 1)[1]
    if "github.com/" in normalized:
        return normalized.split("github.com/", 1)[1]
    raise SystemExit(f"unsupported git remote format: {remote}")


def _register_repo(connection: Any, *, repo: str, workdir: Path, log_dir: Path) -> bool:
    created = False
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS repo_registry (
                repo TEXT PRIMARY KEY,
                workdir TEXT NOT NULL,
                log_dir TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cursor.execute(
            "SELECT repo FROM repo_registry WHERE repo = %s",
            (repo,),
        )
        created = cursor.fetchone() is None
        cursor.execute(
            """
            INSERT INTO repo_registry (repo, workdir, log_dir)
            VALUES (%s, %s, %s)
            ON CONFLICT (repo) DO UPDATE
            SET workdir = EXCLUDED.workdir,
                log_dir = EXCLUDED.log_dir,
                updated_at = NOW()
            """,
            (repo, str(workdir), str(log_dir)),
        )
    commit = getattr(connection, "commit", None)
    if callable(commit):
        commit()
    return created


def _upsert_taskplane_toml(
    *,
    config: TaskplaneConfig,
    repo: str,
    workdir: Path,
    log_dir: Path,
) -> None:
    target = config.source_path or (Path.cwd() / "taskplane.toml")
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    text = existing.rstrip()
    if "[postgres]" not in text and config.postgres_dsn:
        text += (
            ("\n\n" if text else "")
            + "[postgres]\n"
            + f'dsn = "{config.postgres_dsn}"\n'
        )
    text = _upsert_mapping_entry(
        text=text,
        section="console.repo_workdirs",
        key=repo,
        value=str(workdir),
    )
    text = _upsert_mapping_entry(
        text=text,
        section="console.repo_log_dirs",
        key=repo,
        value=str(log_dir),
    )
    default_executor = str(
        config.workflow_repo_default_executor.get(repo) or ""
    ).strip()
    if default_executor:
        text = _upsert_mapping_entry(
            text=text,
            section="workflow.repo_default_executor",
            key=repo,
            value=default_executor,
        )
    target.write_text(text.rstrip() + "\n", encoding="utf-8")


def _upsert_mapping_entry(*, text: str, section: str, key: str, value: str) -> str:
    lines = text.splitlines()
    section_header = f"[{section}]"
    entry = f'"{key}" = "{value}"'

    try:
        section_index = lines.index(section_header)
    except ValueError:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend([section_header, entry])
        return "\n".join(lines)

    insert_at = section_index + 1
    while insert_at < len(lines) and not lines[insert_at].startswith("["):
        current = lines[insert_at].strip()
        if current.startswith(f'"{key}" = '):
            lines[insert_at] = entry
            return "\n".join(lines)
        insert_at += 1
    lines.insert(insert_at, entry)
    return "\n".join(lines)


def _load_status(*, repo: str, dsn: str) -> dict[str, Any]:
    import psycopg
    from psycopg.rows import dict_row

    with cast(Any, psycopg.connect(dsn, row_factory=cast(Any, dict_row))) as connection:
        summary_payload = get_repo_summary(connection, repo=repo)
        jobs_payload = list_running_jobs(connection, repo=repo)
        intents_payload = list_natural_language_intents(connection, repo=repo)
        blocked_tasks = _load_blocked_tasks(connection, repo=repo)
        operator_requests = _load_operator_requests(connection, repo=repo)
        return {
            "repo": repo,
            "summary": summary_payload.get("summary") or {},
            "task_status_counts": summary_payload.get("task_status_counts") or [],
            "jobs": jobs_payload.get("jobs") or [],
            "intents": intents_payload.get("items") or [],
            "blocked_tasks": blocked_tasks,
            "operator_requests": operator_requests,
        }


def _load_blocked_tasks(connection: Any, *, repo: str) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, title, blocked_reason, decision_required
            FROM work_item
            WHERE repo = %s AND status = 'blocked'
            ORDER BY updated_at DESC NULLS LAST, id ASC
            LIMIT 10
            """,
            (repo,),
        )
        rows = cursor.fetchall() or []
    return [dict(row) for row in rows]


def _load_operator_requests(connection: Any, *, repo: str) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT epic_issue_number, reason_code, summary
            FROM operator_request
            WHERE repo = %s AND status = 'open'
            ORDER BY opened_at ASC, reason_code ASC
            LIMIT 10
            """,
            (repo,),
        )
        rows = cursor.fetchall() or []
    return [dict(row) for row in rows]


def _parse_request_ref(raw: str, *, fallback_repo: str) -> tuple[str, int, str]:
    parts = str(raw).split(":")
    if len(parts) < 3 or parts[0] != "epic":
        raise SystemExit("request must be epic:<epic-issue-number>:<reason-code>")
    repo = fallback_repo.strip()
    if not repo:
        raise SystemExit("request handling requires --repo or a git remote-backed repo")
    return repo, int(parts[1]), ":".join(parts[2:])


def _print_intake_guidance(intent: Any) -> None:
    status = str(getattr(intent, "status", "") or "")
    intent_id = str(getattr(intent, "id", "") or "")
    questions = list(getattr(intent, "clarification_questions", ()) or ())
    if status == "awaiting_clarification":
        print("需要你确认 / 补充:")
        for index, question in enumerate(questions, start=1):
            print(f"{index}. {question}")
        print(f'/tp-intake intent={intent_id} answer="..."')
        return
    if status == "awaiting_review":
        print("等待你做 review 决策:")
        print(f"- approve: /tp-intake intent={intent_id} approve")
        print(f'- reject: /tp-intake intent={intent_id} reject "原因"')
        print(f'- revise: /tp-intake intent={intent_id} revise "修改意见"')
        return
    if status == "promoted":
        print("需求已进入 Taskplane 执行图。")
        print("下一步: /tp-status")
        return
    if status == "rejected":
        print("该需求已被拒绝，可重新提交新的 /tp-intake。")


def _print_status(payload: dict[str, Any]) -> None:
    repo = str(payload.get("repo") or "")
    summary = payload.get("summary") or {}
    jobs = list(payload.get("jobs") or [])
    intents = list(payload.get("intents") or [])
    blocked_tasks = list(payload.get("blocked_tasks") or [])
    operator_requests = list(payload.get("operator_requests") or [])

    print(f"Taskplane 状态: {repo}")
    print(f"running jobs: {summary.get('running_job_count', 0)}")
    print(f"blocked tasks: {summary.get('blocked_task_count', 0)}")
    print(f"in progress tasks: {summary.get('in_progress_task_count', 0)}")
    print(f"total tasks: {summary.get('task_count', 0)}")

    if jobs:
        print("\nRunning jobs")
        for job in jobs:
            print(
                f"- job #{job.get('id')} {job.get('job_kind')}"
                f" status={job.get('status')} story={job.get('story_issue_number')}"
                f" work_id={job.get('work_id')} worker={job.get('worker_name')}"
            )

    if intents:
        print("\nPending human actions")
        for item in intents:
            status = str(item.get("status") or "")
            if status not in {"awaiting_clarification", "awaiting_review"}:
                continue
            intent_id = item.get("id") or item.get("intent_id")
            print(f"- {intent_id}: {status} — {item.get('summary')}")
            questions = (
                item.get("clarification_questions_json") or item.get("questions") or []
            )
            if status == "awaiting_clarification":
                for question in questions:
                    print(f"  question: {question}")
                print(f'  next: /tp-intake intent={intent_id} answer="..."')
            elif status == "awaiting_review":
                print(f"  next: /tp-intake intent={intent_id} approve")

    if blocked_tasks:
        print("\nBlocked tasks")
        for task in blocked_tasks:
            print(
                f"- {task.get('id')}: {task.get('title')}"
                f" blocked_reason={task.get('blocked_reason')}"
            )
            if task.get("decision_required"):
                print(
                    "  next: review the related request or revise the intent requirements"
                )

    if operator_requests:
        print("\nOperator requests")
        for request in operator_requests:
            print(
                f"- epic #{request.get('epic_issue_number')} {request.get('reason_code')}:"
                f" {request.get('summary')}"
            )
            print(
                "  next: /tp-intake request="
                f"epic:{request.get('epic_issue_number')}:{request.get('reason_code')} approve"
            )


if __name__ == "__main__":
    entrypoint()
