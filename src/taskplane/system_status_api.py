from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from .hierarchy_api_support import get_hierarchy_api_module

router = APIRouter()


def build_system_status_payload() -> dict[str, Any]:
    api = get_hierarchy_api_module()
    config = api.load_taskplane_config()
    configured_repos = []
    for repo in sorted(
        set(config.console_repo_workdirs.keys()) | set(config.console_repo_log_dirs.keys())
    ):
        workdir_raw = config.console_repo_workdirs.get(repo, "")
        log_dir_raw = config.console_repo_log_dirs.get(repo, "")
        workdir = (
            str(api.resolve_config_path(workdir_raw, source_path=config.source_path))
            if workdir_raw
            else ""
        )
        log_dir = (
            str(api.resolve_config_path(log_dir_raw, source_path=config.source_path))
            if log_dir_raw
            else ""
        )
        configured_repos.append(
            {
                "repo": repo,
                "workdir": workdir,
                "log_dir": log_dir,
                "workdir_exists": bool(workdir and Path(workdir).exists()),
                "log_dir_exists": bool(log_dir and Path(log_dir).exists()),
            }
        )

    repositories: list[str] = []
    database_connected = False
    database_error = ""
    try:
        conn = api._get_connection()
    except Exception as exc:
        database_error = str(exc)
    else:
        try:
            repositories = [
                str(item.get("repo") or "")
                for item in api.list_repositories(conn).get("repositories", [])
                if str(item.get("repo") or "").strip()
            ]
            database_connected = True
        finally:
            conn.close()

    command_status = {
        binary: {
            "available": api.shutil.which(binary) is not None,
            "path": api.shutil.which(binary),
        }
        for binary in ("docker", "psql", "gh", "node", "npm")
    }
    recommendations = [
        "cp taskplane.toml.example taskplane.toml",
        "taskplane-dev up",
        "taskplane-demo seed --repo demo/taskplane --reset",
        "taskplane-doctor --repo demo/taskplane",
    ]

    return {
        "config_source": str(config.source_path) if config.source_path is not None else "",
        "postgres_dsn_configured": bool(config.postgres_dsn.strip()),
        "database_connected": database_connected,
        "database_error": database_error,
        "configured_repos": configured_repos,
        "discovered_repositories": repositories,
        "commands": command_status,
        "dev_compose_file": str(config.dev_compose_file),
        "dev_env_file": str(config.dev_env_file),
        "recommended_actions": recommendations,
    }


@router.get("/api/system/status")
def get_system_status():
    try:
        payload = build_system_status_payload()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return JSONResponse(payload)
