from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import json
import os
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


@dataclass(frozen=True)
class PostgresSettings:
    dsn: str


@dataclass(frozen=True)
class TaskplaneConfig:
    source_path: Path | None = None
    postgres_dsn: str = ""
    console_repo_workdirs: dict[str, str] = field(default_factory=dict)
    console_repo_log_dirs: dict[str, str] = field(default_factory=dict)
    supervisor_repo_story_executor_commands: dict[str, str] = field(
        default_factory=dict
    )
    supervisor_repo_story_verifier_commands: dict[str, str] = field(
        default_factory=dict
    )
    supervisor_repo_story_force_shell_executor: dict[str, bool] = field(
        default_factory=dict
    )
    dev_compose_file: Path = field(
        default_factory=lambda: Path("ops/docker-compose.nocodb.yml")
    )
    dev_env_file: Path = field(default_factory=lambda: Path(".env"))


def load_postgres_settings_from_env() -> PostgresSettings:
    dsn = load_taskplane_config().postgres_dsn.strip()
    if not dsn:
        raise RuntimeError(
            "TASKPLANE_DSN is required (or set [postgres].dsn in taskplane.toml)"
        )
    return PostgresSettings(dsn=dsn)


def load_taskplane_config(config_path: str | Path | None = None) -> TaskplaneConfig:
    resolved_path = _resolve_config_path(config_path)
    payload: dict[str, Any] = {}
    if resolved_path is not None:
        payload = _load_toml_file(resolved_path)

    postgres = _get_table(payload, "postgres")
    console = _get_table(payload, "console")
    supervisor = _get_table(payload, "supervisor")
    dev = _get_table(payload, "dev")

    postgres_dsn = os.getenv("TASKPLANE_DSN", "").strip() or str(
        postgres.get("dsn", "")
    ).strip()
    console_repo_workdirs = _load_mapping(
        env_var="TASKPLANE_CONSOLE_REPO_WORKDIRS_JSON",
        file_value=console.get("repo_workdirs"),
        label="console.repo_workdirs",
    )
    console_repo_log_dirs = _load_mapping(
        env_var="TASKPLANE_CONSOLE_REPO_LOG_DIRS_JSON",
        file_value=console.get("repo_log_dirs"),
        label="console.repo_log_dirs",
    )
    supervisor_repo_story_executor_commands = _load_mapping(
        env_var="TASKPLANE_SUPERVISOR_REPO_STORY_EXECUTOR_COMMANDS_JSON",
        file_value=supervisor.get("repo_story_executor_commands"),
        label="supervisor.repo_story_executor_commands",
    )
    supervisor_repo_story_verifier_commands = _load_mapping(
        env_var="TASKPLANE_SUPERVISOR_REPO_STORY_VERIFIER_COMMANDS_JSON",
        file_value=supervisor.get("repo_story_verifier_commands"),
        label="supervisor.repo_story_verifier_commands",
    )
    supervisor_repo_story_force_shell_executor = _load_bool_mapping(
        env_var="TASKPLANE_SUPERVISOR_REPO_STORY_FORCE_SHELL_EXECUTOR_JSON",
        file_value=supervisor.get("repo_story_force_shell_executor"),
        label="supervisor.repo_story_force_shell_executor",
    )
    dev_compose_file = Path(
        os.getenv("TASKPLANE_DEV_COMPOSE_FILE", "").strip()
        or str(dev.get("compose_file", "ops/docker-compose.nocodb.yml")).strip()
        or "ops/docker-compose.nocodb.yml"
    )
    dev_env_file = Path(
        os.getenv("TASKPLANE_DEV_ENV_FILE", "").strip()
        or str(dev.get("env_file", ".env")).strip()
        or ".env"
    )

    return TaskplaneConfig(
        source_path=resolved_path,
        postgres_dsn=postgres_dsn,
        console_repo_workdirs=console_repo_workdirs,
        console_repo_log_dirs=console_repo_log_dirs,
        supervisor_repo_story_executor_commands=(
            supervisor_repo_story_executor_commands
        ),
        supervisor_repo_story_verifier_commands=(
            supervisor_repo_story_verifier_commands
        ),
        supervisor_repo_story_force_shell_executor=(
            supervisor_repo_story_force_shell_executor
        ),
        dev_compose_file=dev_compose_file,
        dev_env_file=dev_env_file,
    )


def resolve_config_path(path: str | Path, *, source_path: Path | None) -> Path:
    expanded = Path(path).expanduser()
    if expanded.is_absolute():
        return expanded
    if source_path is not None:
        return (source_path.parent / expanded).resolve()
    return expanded.resolve()


def _resolve_config_path(config_path: str | Path | None) -> Path | None:
    if config_path is not None:
        resolved = Path(config_path).expanduser().resolve()
        if not resolved.exists():
            raise RuntimeError(f"taskplane config not found: {resolved}")
        return resolved

    env_path = os.getenv("TASKPLANE_CONFIG", "").strip()
    if env_path:
        resolved = Path(env_path).expanduser().resolve()
        if not resolved.exists():
            raise RuntimeError(f"taskplane config not found: {resolved}")
        return resolved

    default_path = Path.cwd() / "taskplane.toml"
    if default_path.exists():
        return default_path.resolve()
    return None


def _load_toml_file(path: Path) -> dict[str, Any]:
    if tomllib is None:  # pragma: no cover
        raise RuntimeError("Python tomllib is required to parse taskplane.toml")
    with path.open("rb") as handle:
        loaded = tomllib.load(handle)
    if not isinstance(loaded, dict):
        raise RuntimeError(f"taskplane config must be a TOML table: {path}")
    return loaded


def _get_table(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RuntimeError(f"taskplane config section must be a table: {key}")
    return value


def _load_mapping(
    *,
    env_var: str,
    file_value: Any,
    label: str,
) -> dict[str, str]:
    raw_env_value = os.getenv(env_var, "").strip()
    if raw_env_value:
        try:
            candidate = json.loads(raw_env_value)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{env_var} must be valid JSON") from exc
    else:
        candidate = file_value

    if candidate is None:
        return {}
    if not isinstance(candidate, dict):
        raise RuntimeError(f"{label} must be a mapping")

    normalized: dict[str, str] = {}
    for raw_key, raw_value in candidate.items():
        key = str(raw_key).strip()
        value = str(raw_value).strip()
        if key and value:
            normalized[key] = value
    return normalized


def _load_bool_mapping(
    *,
    env_var: str,
    file_value: Any,
    label: str,
) -> dict[str, bool]:
    raw_env_value = os.getenv(env_var, "").strip()
    if raw_env_value:
        try:
            candidate = json.loads(raw_env_value)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{env_var} must be valid JSON") from exc
    else:
        candidate = file_value

    if candidate is None:
        return {}
    if not isinstance(candidate, dict):
        raise RuntimeError(f"{label} must be a mapping")

    normalized: dict[str, bool] = {}
    for raw_key, raw_value in candidate.items():
        key = str(raw_key).strip()
        if not key:
            continue
        if isinstance(raw_value, bool):
            normalized[key] = raw_value
            continue
        value = str(raw_value).strip().lower()
        if value in {"1", "true", "yes", "on"}:
            normalized[key] = True
            continue
        if value in {"0", "false", "no", "off"}:
            normalized[key] = False
            continue
        raise RuntimeError(f"{label} values must be booleans: {key}")
    return normalized
