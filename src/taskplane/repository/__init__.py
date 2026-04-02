"""
Repository package for taskplane.

This package provides repository implementations for the control plane:
- ControlPlaneRepository: Protocol definition
- InMemoryControlPlaneRepository: In-memory implementation for testing
- PostgresControlPlaneRepository: PostgreSQL implementation for production
"""

from __future__ import annotations

from .protocol import (
    ClaimRepository,
    ControlPlaneRepository,
    EpicDecompositionRepository,
    EpicRepository,
    ExecutionRepository,
    StoryDecompositionRepository,
    StoryRepository,
    WorkerRepository,
    WorkStateRepository,
)
from .base import InMemoryControlPlaneRepository
from .postgres import PostgresControlPlaneRepository
from .helpers import _claim_has_path_conflict, _is_claim_active, _is_work_item_eligible

# Re-export with_work_status for backward compatibility
from ..models import with_work_status

__all__ = [
    "WorkStateRepository",
    "ClaimRepository",
    "ExecutionRepository",
    "WorkerRepository",
    "StoryRepository",
    "EpicRepository",
    "StoryDecompositionRepository",
    "EpicDecompositionRepository",
    "ControlPlaneRepository",
    "InMemoryControlPlaneRepository",
    "PostgresControlPlaneRepository",
    "_claim_has_path_conflict",
    "_is_claim_active",
    "_is_work_item_eligible",
    "with_work_status",
]
