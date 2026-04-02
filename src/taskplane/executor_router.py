from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .models import ExecutionContext, WorkItem


@dataclass(frozen=True)
class ExecutorConfig:
    executor_name: str
    executor_type: str
    capabilities: list[str]
    max_concurrent: int
    is_active: bool
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutorMapping:
    task_type: str
    preferred_executor: str
    fallback_executor: str | None
    id: int | None = None
    priority: int = 100
    conditions: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskExecutionProfile:
    task_type: str
    title: str
    lane: str
    wave: str
    complexity: str
    attempt_count: int
    last_failure_reason: str | None
    planned_paths: tuple[str, ...]
    canonical_story_issue_number: int | None
    resume_hint: str | None
    recent_failure_reasons: tuple[str, ...] = ()
    dlq_failure_reasons: tuple[str, ...] = ()
    historical_failure_reasons: tuple[str, ...] = ()
    historical_failure_count: int = 0


class ExecutorRouter:
    def __init__(self, dsn: str, default_executor_name: str | None = None):
        self.dsn = dsn
        self.default_executor_name = default_executor_name
        self._mappings: list[ExecutorMapping] = []
        self._executor_cache: dict[str, ExecutorConfig] = {}
        self._load_mappings()

    def _load_mappings(self) -> None:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        """
                        SELECT *
                        FROM task_executor_mapping
                        ORDER BY priority DESC, id ASC
                        """
                    )
                except Exception:
                    cur.execute("SELECT * FROM task_executor_mapping")
                for row in cur.fetchall():
                    self._mappings.append(
                        ExecutorMapping(
                            task_type=str(row["task_type"] or ""),
                            preferred_executor=row["preferred_executor"],
                            fallback_executor=row["fallback_executor"],
                            id=row.get("id"),
                            priority=int(row.get("priority") or 100),
                            conditions=row["conditions"] or {},
                        )
                    )
                cur.execute("SELECT * FROM executor_registry WHERE is_active = TRUE")
                for row in cur.fetchall():
                    self._executor_cache[row["executor_name"]] = ExecutorConfig(
                        executor_name=row["executor_name"],
                        executor_type=row["executor_type"],
                        capabilities=row["capabilities"] or [],
                        max_concurrent=row["max_concurrent"],
                        is_active=row["is_active"],
                        metadata=row["metadata"] or {},
                    )

    def select_executor(
        self,
        task_type: str,
        *,
        work_item: WorkItem | None = None,
        execution_context: ExecutionContext | None = None,
    ) -> ExecutorConfig | None:
        profile = self._build_task_execution_profile(
            task_type=task_type,
            work_item=work_item,
            execution_context=execution_context,
        )
        candidates: list[tuple[int, int, int, ExecutorMapping]] = []
        for index, mapping in enumerate(self._mappings):
            if not _task_type_matches(mapping.task_type, profile.task_type):
                continue
            match_score = _mapping_match_score(mapping, profile)
            if match_score is None:
                continue
            candidates.append(
                (
                    match_score,
                    1 if _is_exact_task_type_match(mapping.task_type, profile.task_type) else 0,
                    mapping.priority,
                    -index,
                    mapping,
                )
            )

        for _, _, _, _, mapping in sorted(candidates, reverse=True):
            executor = self._resolve_mapping_executor(mapping)
            if executor is not None:
                return executor
        return self._select_default_executor()

    def _resolve_mapping_executor(
        self,
        mapping: ExecutorMapping,
    ) -> ExecutorConfig | None:
        preferred = self._executor_cache.get(mapping.preferred_executor)
        if preferred and preferred.is_active:
            return preferred

        if mapping.fallback_executor:
            fallback = self._executor_cache.get(mapping.fallback_executor)
            if fallback and fallback.is_active:
                return fallback
        return None

    def _select_default_executor(self) -> ExecutorConfig | None:
        if self.default_executor_name:
            default = self._executor_cache.get(self.default_executor_name)
            if default and default.is_active:
                return default

        for executor in self._executor_cache.values():
            if executor.is_active:
                return executor
        return None

    def list_executors(self) -> list[ExecutorConfig]:
        return list(self._executor_cache.values())

    def list_mappings(self) -> list[ExecutorMapping]:
        return list(self._mappings)

    def _build_task_execution_profile(
        self,
        *,
        task_type: str,
        work_item: WorkItem | None,
        execution_context: ExecutionContext | None,
    ) -> TaskExecutionProfile:
        profile = _build_task_execution_profile(
            task_type=task_type,
            work_item=work_item,
            execution_context=execution_context,
        )
        if work_item is None or not self._task_type_uses_history_conditions(profile.task_type):
            return profile
        history = self._load_failure_history(work_item.id)
        historical_failure_reasons = tuple(
            dict.fromkeys(
                [*history.recent_failure_reasons, *history.dlq_failure_reasons]
            )
        )
        return TaskExecutionProfile(
            task_type=profile.task_type,
            title=profile.title,
            lane=profile.lane,
            wave=profile.wave,
            complexity=profile.complexity,
            attempt_count=profile.attempt_count,
            last_failure_reason=profile.last_failure_reason,
            planned_paths=profile.planned_paths,
            canonical_story_issue_number=profile.canonical_story_issue_number,
            resume_hint=profile.resume_hint,
            recent_failure_reasons=history.recent_failure_reasons,
            dlq_failure_reasons=history.dlq_failure_reasons,
            historical_failure_reasons=historical_failure_reasons,
            historical_failure_count=len(history.recent_failure_reasons)
            + len(history.dlq_failure_reasons),
        )

    def _task_type_uses_history_conditions(self, task_type: str) -> bool:
        history_condition_keys = {
            "recent_failure_reasons",
            "dlq_failure_reasons",
            "historical_failure_reasons",
            "min_historical_failures",
            "max_historical_failures",
        }
        for mapping in self._mappings:
            if not _task_type_matches(mapping.task_type, task_type):
                continue
            if history_condition_keys.intersection((mapping.conditions or {}).keys()):
                return True
        return False

    def _load_failure_history(self, work_id: str) -> TaskExecutionProfile:
        recent_failure_reasons: list[str] = []
        dlq_failure_reasons: list[str] = []
        try:
            with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COALESCE(result_payload_json->>'reason_code', '') AS reason_code
                        FROM execution_run
                        WHERE work_id = %s
                          AND status = 'blocked'
                        ORDER BY id DESC
                        LIMIT 8
                        """,
                        (work_id,),
                    )
                    recent_failure_reasons = [
                        normalized
                        for row in cur.fetchall()
                        if (normalized := str(row.get("reason_code") or "").strip().lower())
                    ]
                    cur.execute(
                        """
                        SELECT failure_reason
                        FROM dead_letter_queue
                        WHERE work_id = %s
                        ORDER BY moved_at DESC
                        LIMIT 5
                        """,
                        (work_id,),
                    )
                    dlq_failure_reasons = [
                        normalized
                        for row in cur.fetchall()
                        if (normalized := str(row.get("failure_reason") or "").strip().lower())
                    ]
        except Exception:
            return _empty_history_profile()
        return TaskExecutionProfile(
            task_type="",
            title="",
            lane="",
            wave="",
            complexity="",
            attempt_count=0,
            last_failure_reason=None,
            planned_paths=(),
            canonical_story_issue_number=None,
            resume_hint=None,
            recent_failure_reasons=tuple(recent_failure_reasons),
            dlq_failure_reasons=tuple(dlq_failure_reasons),
            historical_failure_reasons=tuple(
                dict.fromkeys([*recent_failure_reasons, *dlq_failure_reasons])
            ),
            historical_failure_count=len(recent_failure_reasons)
            + len(dlq_failure_reasons),
        )


def _build_task_execution_profile(
    *,
    task_type: str,
    work_item: WorkItem | None,
    execution_context: ExecutionContext | None,
) -> TaskExecutionProfile:
    resolved_task_type = str(
        (
            work_item.task_type
            if work_item is not None and str(work_item.task_type or "").strip()
            else task_type
        )
        or ""
    ).strip()
    return TaskExecutionProfile(
        task_type=resolved_task_type,
        title=(work_item.title if work_item is not None else ""),
        lane=(work_item.lane if work_item is not None else ""),
        wave=(work_item.wave if work_item is not None else ""),
        complexity=(work_item.complexity if work_item is not None else ""),
        attempt_count=(work_item.attempt_count if work_item is not None else 0),
        last_failure_reason=(
            work_item.last_failure_reason.lower()
            if work_item is not None and work_item.last_failure_reason
            else None
        ),
        planned_paths=(
            tuple(str(path) for path in work_item.planned_paths)
            if work_item is not None
            else ()
        ),
        canonical_story_issue_number=(
            work_item.canonical_story_issue_number if work_item is not None else None
        ),
        resume_hint=(
            execution_context.resume_hint.lower()
            if execution_context is not None and execution_context.resume_hint
            else None
        ),
    )


def _task_type_matches(mapping_task_type: str, task_type: str) -> bool:
    normalized_mapping = str(mapping_task_type or "").strip().lower()
    normalized_task_type = str(task_type or "").strip().lower()
    return normalized_mapping in {"", "*", "default", normalized_task_type}


def _is_exact_task_type_match(mapping_task_type: str, task_type: str) -> bool:
    return str(mapping_task_type or "").strip().lower() == str(task_type or "").strip().lower()


def _mapping_match_score(
    mapping: ExecutorMapping,
    profile: TaskExecutionProfile,
) -> int | None:
    conditions = mapping.conditions or {}
    score = 0

    min_attempt_count = conditions.get("min_attempt_count")
    if min_attempt_count is not None:
        if profile.attempt_count < int(min_attempt_count):
            return None
        score += 1

    max_attempt_count = conditions.get("max_attempt_count")
    if max_attempt_count is not None:
        if profile.attempt_count > int(max_attempt_count):
            return None
        score += 1

    if not _matches_optional_set(
        actual=profile.last_failure_reason,
        expected_values=conditions.get("last_failure_reasons"),
    ):
        return None
    if conditions.get("last_failure_reasons"):
        score += 1

    if not _matches_sequence_overlap(
        actual_values=profile.recent_failure_reasons,
        expected_values=conditions.get("recent_failure_reasons"),
    ):
        return None
    if conditions.get("recent_failure_reasons"):
        score += 1

    if not _matches_sequence_overlap(
        actual_values=profile.dlq_failure_reasons,
        expected_values=conditions.get("dlq_failure_reasons"),
    ):
        return None
    if conditions.get("dlq_failure_reasons"):
        score += 1

    if not _matches_sequence_overlap(
        actual_values=profile.historical_failure_reasons,
        expected_values=conditions.get("historical_failure_reasons"),
    ):
        return None
    if conditions.get("historical_failure_reasons"):
        score += 1

    excluded_failure_reasons = conditions.get("exclude_failure_reasons") or []
    if (
        profile.last_failure_reason is not None
        and profile.last_failure_reason in _normalize_string_set(excluded_failure_reasons)
    ):
        return None
    if excluded_failure_reasons:
        score += 1

    min_historical_failures = conditions.get("min_historical_failures")
    if min_historical_failures is not None:
        if profile.historical_failure_count < int(min_historical_failures):
            return None
        score += 1

    max_historical_failures = conditions.get("max_historical_failures")
    if max_historical_failures is not None:
        if profile.historical_failure_count > int(max_historical_failures):
            return None
        score += 1

    if not _matches_title_keywords(
        title=profile.title,
        keywords=conditions.get("title_keywords"),
    ):
        return None
    if conditions.get("title_keywords"):
        score += 1

    if not _matches_path_prefixes(
        planned_paths=profile.planned_paths,
        prefixes=conditions.get("planned_path_prefixes"),
    ):
        return None
    if conditions.get("planned_path_prefixes"):
        score += 1

    requires_story_workspace = conditions.get("requires_story_workspace")
    if requires_story_workspace is not None:
        if bool(requires_story_workspace) != (
            profile.canonical_story_issue_number is not None
        ):
            return None
        score += 1

    if not _matches_optional_set(
        actual=profile.complexity.lower() if profile.complexity else None,
        expected_values=conditions.get("complexities"),
    ):
        return None
    if conditions.get("complexities"):
        score += 1

    if not _matches_optional_set(
        actual=profile.lane.lower() if profile.lane else None,
        expected_values=conditions.get("lanes"),
    ):
        return None
    if conditions.get("lanes"):
        score += 1

    if not _matches_optional_set(
        actual=profile.wave.lower() if profile.wave else None,
        expected_values=conditions.get("waves"),
    ):
        return None
    if conditions.get("waves"):
        score += 1

    if not _matches_optional_set(
        actual=profile.resume_hint,
        expected_values=conditions.get("resume_hints"),
    ):
        return None
    if conditions.get("resume_hints"):
        score += 1

    return score


def _matches_optional_set(
    *,
    actual: str | None,
    expected_values: Any,
) -> bool:
    normalized = _normalize_string_set(expected_values)
    if not normalized:
        return True
    if actual is None:
        return False
    return actual.lower() in normalized


def _matches_sequence_overlap(
    *,
    actual_values: tuple[str, ...],
    expected_values: Any,
) -> bool:
    normalized = _normalize_string_set(expected_values)
    if not normalized:
        return True
    return any(str(value or "").strip().lower() in normalized for value in actual_values)


def _matches_title_keywords(
    *,
    title: str,
    keywords: Any,
) -> bool:
    normalized_keywords = _normalize_string_set(keywords)
    if not normalized_keywords:
        return True
    title_lower = title.lower()
    return all(keyword in title_lower for keyword in normalized_keywords)


def _matches_path_prefixes(
    *,
    planned_paths: tuple[str, ...],
    prefixes: Any,
) -> bool:
    normalized_prefixes = _normalize_string_set(prefixes)
    if not normalized_prefixes:
        return True
    lowered_paths = [path.lower() for path in planned_paths]
    return any(
        any(path.startswith(prefix) for path in lowered_paths)
        for prefix in normalized_prefixes
    )


def _normalize_string_set(values: Any) -> set[str]:
    if values is None:
        return set()
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list | tuple | set):
        return set()
    return {
        str(value).strip().lower()
        for value in values
        if str(value or "").strip()
    }


def _empty_history_profile() -> TaskExecutionProfile:
    return TaskExecutionProfile(
        task_type="",
        title="",
        lane="",
        wave="",
        complexity="",
        attempt_count=0,
        last_failure_reason=None,
        planned_paths=(),
        canonical_story_issue_number=None,
        resume_hint=None,
    )
