"""
Backward compatibility layer for repository.

This module now re-exports from the repository package for backward compatibility.
New code should import from the repository package directly:
    from taskplane.repository import (
        ControlPlaneRepository,
        InMemoryControlPlaneRepository,
        PostgresControlPlaneRepository,
    )
"""

from __future__ import annotations

from .repository import (
    ClaimRepository,
    ControlPlaneRepository,
    EpicDecompositionRepository,
    EpicRepository,
    ExecutionRepository,
    InMemoryControlPlaneRepository,
    PostgresControlPlaneRepository,
    ReadyStateSyncRepository,
    StoryDecompositionRepository,
    StoryRepository,
    SupervisorSchedulingRepository,
    WorkerRepository,
    WorkStateRepository,
    _claim_has_path_conflict,
    _is_claim_active,
    _is_work_item_eligible,
    with_work_status,
)

# Backward compatibility export
from .models import REQUEUE_BACKOFF

__all__ = [
    "WorkStateRepository",
    "ReadyStateSyncRepository",
    "ClaimRepository",
    "ExecutionRepository",
    "WorkerRepository",
    "StoryRepository",
    "EpicRepository",
    "StoryDecompositionRepository",
    "EpicDecompositionRepository",
    "SupervisorSchedulingRepository",
    "ControlPlaneRepository",
    "InMemoryControlPlaneRepository",
    "PostgresControlPlaneRepository",
    "_claim_has_path_conflict",
    "_is_claim_active",
    "_is_work_item_eligible",
    "with_work_status",
    "REQUEUE_BACKOFF",
]
