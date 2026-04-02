from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class CheckResult:
    check_type: str
    passed: bool
    command: str
    output_digest: str
    exit_code: int | None = None
    elapsed_ms: int | None = None


@dataclass(frozen=True)
class FailureReport:
    work_id: str
    attempt: int
    reason_code: str
    summary: str
    execution_journal: str = ""
    artifacts: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    test_output: str | None = None
    timestamp: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> FailureReport:
        data = json.loads(raw)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class PatchProposal:
    work_id: str
    attempt: int
    patch_diff: str
    changed_files: list[str] = field(default_factory=list)
    rationale: str = ""
    risk_level: Literal["low", "medium", "high"] = "medium"
    verification_hints: list[str] = field(default_factory=list)
    author_agent: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> PatchProposal:
        data = json.loads(raw)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class VerificationResult:
    work_id: str
    run_id: int
    checks: list[CheckResult] = field(default_factory=list)
    overall_passed: bool = False
    evidence_artifacts: list[str] = field(default_factory=list)
    summary: str = ""

    def to_json(self) -> str:
        data = asdict(self)
        data["checks"] = [asdict(c) for c in self.checks]
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> VerificationResult:
        data = json.loads(raw)
        checks = [CheckResult(**c) for c in data.pop("checks", [])]
        return cls(
            checks=checks,
            **{k: v for k, v in data.items() if k in cls.__dataclass_fields__},
        )


@dataclass(frozen=True)
class TaskSummary:
    work_id: str
    outcome: Literal["done", "failed", "blocked"]
    changed_files: list[str] = field(default_factory=list)
    commit_sha: str | None = None
    verification_passed: bool = False
    artifacts: list[str] = field(default_factory=list)
    summary: str = ""
    attempt_count: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> TaskSummary:
        data = json.loads(raw)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
