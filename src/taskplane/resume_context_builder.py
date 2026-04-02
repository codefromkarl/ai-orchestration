from __future__ import annotations

from collections.abc import Callable

from .models import ExecutionSession
from .protocols import SessionManagerProtocol


def build_store_backed_resume_context_builder(
    *,
    dsn: str | None,
    session_manager: SessionManagerProtocol,
    artifact_limit: int = 6,
    max_chars: int = 1600,
) -> Callable[[ExecutionSession], str] | None:
    if not dsn:
        return None

    try:
        from .artifact_store import ArtifactStore
        from .context_store import ContextStore
    except Exception:
        return None

    artifact_store = ArtifactStore(dsn=dsn)
    context_store = ContextStore(dsn=dsn)

    def builder(session: ExecutionSession) -> str:
        fallback = session_manager.build_resume_context(session.id)
        try:
            artifacts = artifact_store.lookup(
                work_id=session.work_id,
                limit=artifact_limit,
            )
            enriched = context_store.build_resume_context(
                session.work_id,
                artifacts=artifacts,
                max_chars=max_chars,
            ).strip()
        except Exception:
            return fallback

        if not enriched:
            return fallback
        if not fallback:
            return enriched
        return (
            f"Session state:\n{fallback}\n\n"
            f"Conversation context:\n{enriched}"
        )

    return builder
