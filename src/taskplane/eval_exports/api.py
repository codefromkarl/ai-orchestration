from __future__ import annotations

from datetime import UTC, datetime
from typing import Final
from typing import Any

from .schemas import EvalExportEndpoint, EvalExportEnvelope


EVAL_EXPORT_CURSOR_PARAMS: Final[dict[str, str]] = {
    "work_items": "after_work_id",
    "attempts": "after_run_id",
    "verifications": "after_id",
}

__all__ = [
    "EVAL_EXPORT_CURSOR_PARAMS",
    "build_collection_response",
    "build_eval_export_endpoints",
]


def build_eval_export_endpoints() -> tuple[EvalExportEndpoint, ...]:
    return (
        EvalExportEndpoint(
            path="/api/eval/v1/work-items",
            description="List work snapshot exports",
            cursor_param=EVAL_EXPORT_CURSOR_PARAMS["work_items"],
        ),
        EvalExportEndpoint(
            path="/api/eval/v1/work-items/{work_id}",
            description="Get a single work snapshot export",
        ),
        EvalExportEndpoint(
            path="/api/eval/v1/attempts",
            description="List execution attempt exports",
            cursor_param=EVAL_EXPORT_CURSOR_PARAMS["attempts"],
        ),
        EvalExportEndpoint(
            path="/api/eval/v1/verifications",
            description="List verification result exports",
            cursor_param=EVAL_EXPORT_CURSOR_PARAMS["verifications"],
        ),
    )


def build_collection_response(
    items: list[Any], *, next_cursor: str | None = None, has_more: bool = False
) -> dict[str, Any]:
    normalized_items = [
        item.to_dict() if hasattr(item, "to_dict") else item for item in items
    ]
    envelope = EvalExportEnvelope(
        data=normalized_items,
        emitted_at=datetime.now(UTC).isoformat(),
        next_cursor=next_cursor,
        has_more=has_more,
    )
    return envelope.to_dict()
