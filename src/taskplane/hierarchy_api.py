from __future__ import annotations

from importlib import import_module
import os
from pathlib import Path
import shutil
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from . import actions_api_routes
from . import governance_api_routes
from . import hierarchy_api_support
from . import hierarchy_issue_api_routes
from . import intake_api_routes
from . import observability_api_routes
from . import read_api_routes
from . import system_status_api

_console_read_api = import_module("taskplane.console_read_api")
_console_actions = import_module("taskplane.console_actions")
_eval_exports_read_api = import_module("taskplane.eval_exports.read_api")
_governance_priority_api = import_module("taskplane.governance_priority_api")
_governance_health = import_module("taskplane.governance_health")
_orphan_coordinator = import_module("taskplane.orphan_coordinator")
_auto_split_trigger = import_module("taskplane.auto_split_trigger")
_governance_decision_engine = import_module("taskplane.governance_decision_engine")
_console_api_internal = import_module("taskplane._console_api_internal")
_settings = import_module("taskplane.settings")
_factory = import_module("taskplane.factory")
_intake_service = import_module("taskplane.intake_service")

ConsoleNotFoundError = _console_read_api.ConsoleNotFoundError
ConsoleActionConfigurationError = _console_actions.ConsoleActionConfigurationError
ConsoleActionConflictError = _console_actions.ConsoleActionConflictError
get_epic_detail = _console_read_api.get_epic_detail
get_repo_summary = _console_read_api.get_repo_summary
get_story_detail = _console_read_api.get_story_detail
get_task_detail = _console_read_api.get_task_detail
get_job_detail = _console_read_api.get_job_detail
list_epic_rows = _console_read_api.list_epic_rows
list_epic_story_tree = _console_read_api.list_epic_story_tree
list_running_jobs = _console_read_api.list_running_jobs
list_runtime_observability = _console_read_api.list_runtime_observability
list_executor_routing_profiles = _console_read_api.list_executor_routing_profiles
list_executor_selection_events = _console_read_api.list_executor_selection_events
list_repositories = _console_read_api.list_repositories
list_execution_attempt_exports = _eval_exports_read_api.list_execution_attempt_exports
get_work_snapshot_export = _eval_exports_read_api.get_work_snapshot_export
list_verification_result_exports = (
    _eval_exports_read_api.list_verification_result_exports
)
list_work_snapshot_exports = _eval_exports_read_api.list_work_snapshot_exports
run_epic_split_action = _console_actions.run_epic_split_action
run_story_split_action = _console_actions.run_story_split_action
run_task_retry_action = _console_actions.run_task_retry_action
run_operator_request_ack_action = _console_actions.run_operator_request_ack_action
list_portfolio_summary = _console_read_api.list_portfolio_summary
list_ai_decisions = _console_read_api.list_ai_decisions
list_notifications = _console_read_api.list_notifications
list_agent_status = _console_read_api.list_agent_status
get_failed_notifications = _console_read_api.get_failed_notifications
get_agent_efficiency_stats = _console_read_api.get_agent_efficiency_stats
load_taskplane_config = _settings.load_taskplane_config
resolve_config_path = _settings.resolve_config_path
build_postgres_repository = _factory.build_postgres_repository
NaturalLanguageIntakeService = _intake_service.NaturalLanguageIntakeService
build_default_intake_analyzer = _intake_service.build_default_analyzer
_normalize_value = _console_api_internal._normalize_value
_load_issues = hierarchy_api_support.load_issues
_load_work_items_by_issue = hierarchy_api_support.load_work_items_by_issue
_build_node = hierarchy_api_support.build_issue_node

list_natural_language_intents = intake_api_routes.list_natural_language_intents
IntentSubmitRequest = intake_api_routes.IntentSubmitRequest
IntentAnswerRequest = intake_api_routes.IntentAnswerRequest
IntentApproveRequest = intake_api_routes.IntentApproveRequest
IntentRejectRequest = intake_api_routes.IntentRejectRequest
IntentReviseRequest = intake_api_routes.IntentReviseRequest
_serialize_intent = intake_api_routes.serialize_intent
_build_system_status_payload = system_status_api.build_system_status_payload

get_hierarchy = hierarchy_issue_api_routes.get_hierarchy
get_issue = hierarchy_issue_api_routes.get_issue

get_repositories = read_api_routes.get_repositories
get_repository_summary = read_api_routes.get_repository_summary
get_repository_epics = read_api_routes.get_repository_epics
get_repository_epic_story_tree = read_api_routes.get_repository_epic_story_tree
get_repository_running_jobs = read_api_routes.get_repository_running_jobs
get_repository_runtime_observability = (
    read_api_routes.get_repository_runtime_observability
)
get_eval_export_work_items = read_api_routes.get_eval_export_work_items
get_eval_export_work_item = read_api_routes.get_eval_export_work_item
get_eval_export_attempts = read_api_routes.get_eval_export_attempts
get_eval_export_verifications = read_api_routes.get_eval_export_verifications
get_repository_epic_detail = read_api_routes.get_repository_epic_detail
get_repository_story_detail = read_api_routes.get_repository_story_detail
get_repository_task_detail = read_api_routes.get_repository_task_detail
get_repository_job_detail = read_api_routes.get_repository_job_detail
get_work_items = read_api_routes.get_work_items

get_governance_priority = governance_api_routes.get_governance_priority
get_governance_health = governance_api_routes.get_governance_health
resolve_governance_orphans = governance_api_routes.resolve_governance_orphans
evaluate_auto_splits_endpoint = governance_api_routes.evaluate_auto_splits_endpoint
run_governance_decisions = governance_api_routes.run_governance_decisions

get_system_status = system_status_api.get_system_status

post_repository_epic_split = actions_api_routes.post_repository_epic_split
post_repository_story_split = actions_api_routes.post_repository_story_split
post_repository_task_retry = actions_api_routes.post_repository_task_retry
post_operator_request_ack = actions_api_routes.post_operator_request_ack

get_portfolio_summary = observability_api_routes.get_portfolio_summary
get_ai_decisions = observability_api_routes.get_ai_decisions
get_notifications = observability_api_routes.get_notifications
get_failed_notifications_route = observability_api_routes.get_failed_notifications_route
get_agent_status = observability_api_routes.get_agent_status
get_agent_efficiency_stats_route = (
    observability_api_routes.get_agent_efficiency_stats_route
)
task_timeline = observability_api_routes.task_timeline
global_events = observability_api_routes.global_events
executor_routing_profiles = observability_api_routes.executor_routing_profiles
executor_selection_events = observability_api_routes.executor_selection_events
dlq_list = observability_api_routes.dlq_list

get_natural_language_intents = intake_api_routes.get_natural_language_intents
submit_natural_language_intent = intake_api_routes.submit_natural_language_intent
answer_natural_language_intent = intake_api_routes.answer_natural_language_intent
approve_natural_language_intent = intake_api_routes.approve_natural_language_intent
reject_natural_language_intent = intake_api_routes.reject_natural_language_intent
revise_natural_language_intent = intake_api_routes.revise_natural_language_intent

app = FastAPI(title="Stardrifter Issue Hierarchy")

for router in (
    system_status_api.router,
    hierarchy_issue_api_routes.router,
    read_api_routes.router,
    governance_api_routes.router,
    actions_api_routes.router,
    observability_api_routes.router,
    intake_api_routes.router,
):
    app.include_router(router)

_STATIC_DIR = Path(__file__).parent / "static"


def _read_html_asset(filename: str, repo: str = "") -> str:
    html_path = _STATIC_DIR / filename
    if not html_path.exists():
        raise HTTPException(status_code=500, detail=f"{filename} not found")
    html = html_path.read_text(encoding="utf-8")
    return html.replace('"__DEFAULT_REPO__"', f'"{repo}"')


def _get_connection() -> Any:
    dsn = os.getenv("TASKPLANE_DSN", "").strip()
    if not dsn:
        raise RuntimeError("TASKPLANE_DSN is required")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("psycopg is required") from exc
    return cast(Any, psycopg.connect(dsn, row_factory=cast(Any, dict_row)))


def _create_intake_service(repository: Any) -> Any:
    analyzer = build_default_intake_analyzer(repository)
    return NaturalLanguageIntakeService(repository=repository, analyzer=analyzer)


def _build_intake_repository() -> Any:
    return build_postgres_repository(dsn=os.getenv("TASKPLANE_DSN", "").strip())


def _close_connection(connection: Any) -> None:
    close = getattr(connection, "close", None)
    if callable(close):
        close()


@app.get("/", response_class=HTMLResponse)
def index(repo: str = Query(default="")):
    return HTMLResponse(content=_read_html_asset("console.html", repo=repo))


@app.get("/console", response_class=HTMLResponse)
def console_index(repo: str = Query(default="")):
    return HTMLResponse(content=_read_html_asset("console.html", repo=repo))


@app.get("/hierarchy", response_class=HTMLResponse)
def hierarchy_index(repo: str = Query(default="")):
    return HTMLResponse(content=_read_html_asset("hierarchy.html", repo=repo))


@app.get("/console.css")
def console_css():
    css_path = _STATIC_DIR / "console.css"
    if not css_path.exists():
        raise HTTPException(status_code=500, detail="console.css not found")
    return HTMLResponse(
        content=css_path.read_text(encoding="utf-8"), media_type="text/css"
    )


@app.get("/console.bundle.js")
def console_bundle_js():
    js_path = _STATIC_DIR / "console.bundle.js"
    if not js_path.exists():
        raise HTTPException(status_code=500, detail="console.bundle.js not found")
    return HTMLResponse(
        content=js_path.read_text(encoding="utf-8"),
        media_type="application/javascript",
    )
