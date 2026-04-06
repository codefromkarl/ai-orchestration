# Eval Boundary: Taskplane Kernel vs External EvalOps

## Status

Proposed

## Purpose

This document defines the boundary between:

1. **Taskplane as the authoritative orchestration and evaluation-fact substrate**
2. **A separate EvalOps layer that consumes Taskplane facts and produces derived judgments**

The goal is to preserve Taskplane's correctness boundary while still enabling richer benchmarking, regression analysis, reporting, and experiment workflows.

This document follows the existing architecture and correctness model already established in:

- `docs/substrate-architecture.md`
- `docs/task-orchestrator-correctness-and-verification-design.md`
- `docs/ai-task-testing-strategy.md`
- `docs/mvp-design.md`

---

## Core rule

Split by **truth ownership**, not by UI location, file count, or implementation convenience.

- **Taskplane answers:** _What happened in the runtime, and what is the authoritative current state?_
- **EvalOps answers:** _Was it good, is it improving, and how does one version compare to another?_

If a capability is required for claim/lease/finalize correctness, verifier-backed completion, approval state, or canonical attempt history, it belongs in Taskplane.

If a capability is derived from those facts for analytics, benchmarking, scoring, comparison, or reporting, it belongs in EvalOps.

---

## Why this boundary exists

Taskplane already defines completion in control-plane terms rather than self-reporting terms.

The existing repository/testing model anchors success to:

> repository-owned terminalization + verifier-backed terminal state + observable attempt record

That means Taskplane already owns the evaluation **kernel**:

- execution facts
- verification facts
- attempt lifecycle metadata
- terminalization correctness
- approval and closure evidence

But the repository also explicitly says the current reporting surface is only a starting point, not a full analytics platform. The minimal attempt reporting and runtime observability surfaces should therefore remain small and operational, while richer evaluation products are built downstream.

---

## What Taskplane owns

Taskplane is the **source of truth** for orchestration and evaluation facts.

### 1. Authoritative work state

Taskplane owns the canonical current state of work items, including:

- `pending`
- `ready`
- `in_progress`
- `verifying`
- `blocked`
- `awaiting_approval`
- `done`

This state must continue to be repository-owned and transactionally finalized.

### 2. Attempt lifecycle truth

Taskplane owns the authoritative lifecycle of execution attempts, including:

- `attempt_count`
- `last_failure_reason`
- `next_eligible_at`
- lease ownership and staleness checks
- retry vs non-retry classification used by runtime state transitions

These are correctness fields, not reporting conveniences.

### 3. Execution facts

Taskplane owns canonical execution history, including:

- `ExecutionRun`
- executor identity / command reference
- timing and exit metadata
- structured result payloads
- changed-path and partial artifact references where available

### 4. Verification facts

Taskplane owns canonical verification history, including:

- `VerificationEvidence`
- verification command reference
- pass/fail result
- normalized verification outcome classification
- output digests and timing metadata

Verification evidence remains the authoritative basis for completion, not the executor's self-report.

### 5. Approval and closure evidence

Taskplane owns:

- `awaiting_approval` state
- approval events
- commit linkage
- PR linkage
- closure transitions derived from repository rules

### 6. Artifact and trace references

Taskplane owns the index of runtime evidence, including references to:

- stdout/stderr artifacts
- traces
- verification results
- task summaries
- other execution-linked artifacts

Large payloads may live in object storage or external systems, but the canonical reference and linkage belong to Taskplane.

### 7. Fact normalization

Taskplane owns the canonical normalization layer that maps executor/verifier-specific outputs into stable runtime facts:

- outcome taxonomy
- reason codes
- approval-required semantics
- retryability semantics used by control-plane logic

This normalization is part of the substrate contract.

---

## What EvalOps owns

EvalOps is a **consumer of Taskplane facts**, not the source of runtime truth.

### 1. Dataset and case management

EvalOps owns:

- dataset/case registry
- scenario definitions
- labeled examples
- curated replay sets
- benchmark suite membership

### 2. Experiments and comparisons

EvalOps owns:

- offline experiments
- replay jobs
- prompt/model/version comparisons
- cross-executor comparisons
- verifier profile comparisons

### 3. Scoring and judgment

EvalOps owns:

- scorer registry
- judge outputs
- human review annotations for evaluation
- quality labels
- rubric-based assessments

These are judgments derived from Taskplane facts, not runtime facts themselves.

### 4. Regression and baseline analysis

EvalOps owns:

- regression baselines
- release-to-release deltas
- historical cohort comparisons
- benchmark trend analysis

### 5. Reporting and dashboards

EvalOps owns:

- reporting UI
- dashboards
- scorecards
- release gating views
- quality comparisons across prompts/models/executors/suites

Taskplane may retain operational runtime observability views, but should not grow into the primary home for deep evaluation analytics.

---

## Capabilities that stay in Taskplane

The following capabilities are part of the substrate and must remain inside Taskplane:

- repository-owned claim / lease / finalize
- execution and verification evidence persistence
- retry metadata and current eligibility state
- approval event recording
- canonical state transitions
- current work snapshots
- artifact references tied to attempts
- stable export surfaces for runtime facts
- deterministic correctness tests for repository / worker / verifier behavior

These capabilities must continue to work even if the external EvalOps layer is unavailable.

---

## Capabilities that move to EvalOps

The following capabilities should be built outside the Taskplane control plane:

- dataset/case registry
- benchmark suite management
- scenario definitions
- offline replay/experiment execution
- scorer/judge registries
- regression baselines
- cross-model and cross-prompt comparisons
- rich dashboards and long-horizon reporting
- CI/release gating based on evaluation thresholds
- annotation/review workflows for evaluation operations

These capabilities depend on Taskplane facts, but should not be required for Taskplane runtime correctness.

---

## Gray-area rule

Some capabilities appear near the boundary. Use this rule:

### Keep it in Taskplane if:

1. It changes authoritative runtime state
2. It is required for verifier-backed completion
3. It affects retry, lease, or finalize semantics
4. The system cannot execute safely without it

### Move it to EvalOps if:

1. It interprets facts rather than producing them
2. It compares multiple runs, prompts, models, or baselines
3. It relies on curated datasets or scoring assets
4. It can be delayed or recomputed without affecting runtime correctness

---

## Minimal export contract

Taskplane should expose a **stable fact export surface** rather than embedding a full evaluation platform.

### Export object families

At minimum, Taskplane should be able to export:

1. `WorkSnapshot`
2. `ExecutionAttempt`
3. `VerificationResult`

Optional later exports:

4. `ApprovalEvent`
5. `ArtifactReference`
6. `WorkStateTransition`

### Export design constraints

All exported objects should:

- be versioned (`schema_version`)
- carry canonical IDs (`work_id`, `run_id`, etc.)
- use append-only facts for attempts/verifications/events
- separate snapshots from historical event records
- avoid derived scoring or benchmark metadata

### Non-goal for export contracts

Exports should describe **what happened**, not **how good it was**.

Therefore exported Taskplane facts should not include:

- eval scores
- benchmark labels
- regression classifications
- prompt/model rankings
- release gate outcomes

Those belong to the downstream EvalOps schema.

---

## API boundary recommendation

Taskplane should distinguish between:

### 1. Fact export APIs

Read-only APIs for runtime evidence and snapshots, for example:

- `GET /api/eval/v1/work-items`
- `GET /api/eval/v1/work-items/{work_id}`
- `GET /api/eval/v1/attempts`
- `GET /api/eval/v1/verifications`

These are for downstream ingestion and analysis.

### 2. Control APIs

If EvalOps later needs to influence Taskplane, it must do so through explicit control commands, for example:

- `POST /api/control/v1/work-items/{work_id}/request-retry`
- `POST /api/control/v1/work-items/{work_id}/request-reverify`
- `POST /api/control/v1/work-items/{work_id}/record-approval`

EvalOps must never directly mutate Taskplane tables.

---

## Anti-patterns

The following are explicitly discouraged.

### 1. Putting derived evaluation fields into control-plane core tables

Do not expand `work_item`, `execution_run`, or `verification_evidence` with fields such as:

- `eval_score`
- `benchmark_suite`
- `quality_label`
- `regression_status`
- `model_rank`

These are not runtime truths.

### 2. Letting external systems write Taskplane database state directly

No external evaluation system should:

- update `work_item.status`
- rewrite attempt metadata
- inject terminal states
- bypass repository finalization paths

### 3. Mixing facts and judgments in the same contract

Do not make a single schema or API response carry both:

- raw execution/verification facts
- downstream quality scoring and benchmark conclusions

These evolve at different speeds and serve different correctness guarantees.

### 4. Making EvalOps a dependency for safe execution

Taskplane must remain able to:

- claim
- execute
- verify
- finalize
- retry
- approve

even if the external EvalOps layer is unavailable.

### 5. Growing operational runtime observability into a full analytics platform inside Taskplane

Taskplane may keep operational console/CLI surfaces, but should not become the long-term home for:

- benchmark management
- experiment management
- scoring dashboards
- cross-version comparison UIs

---

## Relationship to current repository surfaces

The current repository already contains the beginnings of this split:

- control-plane fact persistence in schema/models/repository
- runtime observability surfaces in console/API views
- a minimal reporting helper in `src/taskplane/attempt_report.py`

This should be interpreted as:

- **Taskplane already has an Eval kernel**
- **Taskplane does not yet need to become a full EvalOps platform**

The current attempt report and runtime observability surfaces should remain small, operational, and fact-oriented.

---

## Phased roadmap

### Milestone 1: Boundary freeze

Document and enforce that Taskplane owns runtime facts and EvalOps owns derived evaluation assets.

Deliverables:

- this boundary document
- canonical outcome/reason taxonomy documentation
- explicit non-goals for internal analytics expansion

### Milestone 2: Stable fact export surface

Add versioned read-only exports for:

- work snapshots
- execution attempts
- verification results

Deliverables:

- export schemas
- cursor-based export APIs
- tests for schema stability and incremental reads

### Milestone 3: External EvalOps read models

Build an external consumer that ingests Taskplane facts and produces read models for:

- attempt health
- verification health
- blocked work analysis
- executor/verifier comparisons

Deliverables:

- raw fact ingestion
- derived analytics tables/views
- initial dashboards

### Milestone 4: Benchmarking and regression platform

Add external support for:

- datasets/cases
- benchmark suites
- experiments
- scorers/judges
- regression baselines

Deliverables:

- dataset registry
- experiment history
- compare/report flows

### Milestone 5: Controlled feedback loop

Allow EvalOps to influence Taskplane only through explicit, auditable commands.

Deliverables:

- control API endpoints
- annotation/command logs
- limited, policy-governed automation

---

## Adoption rule for future changes

For any new evaluation-related feature, answer these questions before implementation:

1. Does it define or mutate authoritative runtime truth?
2. Is it required for verifier-backed completion or retry/finalize correctness?
3. Would Taskplane still need it if EvalOps did not exist?
4. Is it a fact, or a judgment derived from facts?

If the answer points to runtime truth, keep it in Taskplane.

If the answer points to evaluation interpretation, comparison, or reporting, build it in EvalOps.

---

## Bottom line

Taskplane should produce **canonical, observable, verifier-backed execution facts**.

EvalOps should consume those facts to produce **judgments, comparisons, baselines, and reports**.

Taskplane is the truth owner for orchestration state.
EvalOps is the truth owner for downstream evaluation products.
