# Task Orchestrator Correctness and Verification Design

For the engineering boundary policy that defines which layers must be strictly enforced and which layers should retain flexibility, see:

- `docs/adr/0001-engineering-boundaries.md`

For the specific boundary between Taskplane's authoritative runtime facts and a separate downstream EvalOps layer, see:

- `docs/eval-boundary.md`

## Purpose

This document defines how the PostgreSQL-backed task orchestrator should guarantee execution correctness, prevent false completion, and systematically verify completed work.

The core principle is:

> A task is not complete because an executor claims success. A task is complete only when the control plane records verifier-backed completion evidence or an explicit human approval decision.

This design separates responsibilities into three layers:

- **Orchestrator control plane**: task state machine, claim/lease, retries, finalization
- **Execution layer**: task execution and result production
- **Verification layer**: automated checks and approval gates that determine whether work may enter a terminal success state

---

## Goals

### Primary goals

- prevent duplicate execution under concurrent workers
- prevent stale workers from overwriting newer results
- prevent tasks from entering `done` without verification evidence
- support retryable failures without losing attempt history
- support tasks that require human approval after automated checks
- keep verification logic pluggable rather than hard-coded into the scheduler core

### Non-goals

- embedding all testing logic directly in the scheduler core
- treating executor self-report as authoritative completion
- collapsing all failure modes into a single generic `blocked` state
- using informal logs or comments as a substitute for approval state

---

## Core principles

### 1. Repository owns truth

Database state is the authoritative source of task status.

Workers, executors, and verifiers may propose outcomes, but only repository finalization methods may write terminal state.

### 2. Lease ownership is required for state advancement

Any in-flight task must have an active lease.

Only the current lease holder may transition a task through execution or verification and write final state.

### 3. Completion requires evidence

A task may enter `done` only if one of the following is true:

- verification evidence for the current attempt is present and sufficient
- a human approval decision is recorded for a task in `awaiting_approval`

### 4. Verification is part of the lifecycle

Verification is not an optional post-processing job.

It is a formal state transition in the main task lifecycle.

### 5. Verification logic is pluggable

The orchestrator must enforce the existence of verification, but it must not hard-code every verification implementation.

Different task types may use different verifiers.

---

## State model

The orchestrator uses the following task states:

- `pending`: not yet eligible to run
- `ready`: eligible to be claimed by a worker
- `in_progress`: currently claimed and executing
- `verifying`: execution finished, post-execution verification in progress
- `awaiting_approval`: automated checks are complete, but human approval is required
- `blocked`: external condition prevents progress
- `failed`: the current attempt is definitively unsuccessful
- `done`: the task is complete

### State semantics

#### `pending`

Used for:

- unmet dependencies
- retry backoff windows
- recovered expired leases
- retryable failures awaiting re-eligibility

#### `ready`

Used only when:

- dependencies are satisfied
- backoff has expired
- the task is not actively leased
- guardrails allow execution

#### `in_progress`

Used when:

- a worker has successfully claimed the task
- the task has an active lease
- the worker is executing the task

#### `verifying`

Used when:

- execution has produced an output
- the task is under post-execution validation
- the task remains lease-owned during validation

#### `awaiting_approval`

Used when:

- automated verification has produced sufficient evidence
- final completion still requires a human decision

#### `blocked`

Used when:

- external conditions must change before work may continue
- examples include required approval, missing input, or policy constraints

#### `failed`

Used when:

- execution or verification conclusively proves the attempt did not satisfy requirements

#### `done`

Used only when:

- verifier-backed evidence exists for the current attempt
- or an approval event finalizes the task after `awaiting_approval`

---

## Allowed state transitions

### Main success path

`pending -> ready -> in_progress -> verifying -> done`

### Retry path

`in_progress -> pending`

`verifying -> pending`

Used only for retryable failures such as:

- timeout
- lease loss / worker crash
- verifier infrastructure failure

### Approval path

`verifying -> awaiting_approval -> done`

### Failure path

`in_progress -> failed`

`verifying -> failed`

`awaiting_approval -> failed`

### Blocked path

`in_progress -> blocked`

`blocked -> ready`

---

## Data model

### `work_items`

Stores current control-plane state:

- identity
- current status
- attempt count
- lease fields
- retry fields
- blocking and decision metadata

This table represents current truth, not full history.

### `work_dependencies`

Stores task dependency edges:

- `work_id`
- `depends_on_work_id`
- dependency type

### `work_targets`

Stores target resources for conflict detection and guardrails:

- target path
- target type
- frozen flag
- approval-required flag

### `execution_runs`

Stores one record per execution attempt:

- work id
- attempt number
- worker name
- lease token
- execution result
- digests
- failure classification

### `verification_evidence`

Stores one or more verification records per attempt:

- work id
- attempt number
- step number
- check type
- command
- pass/fail
- digests
- failure classification

### `approval_events`

Stores explicit approval decisions:

- approver
- decision
- reason
- attempt number

### `work_state_transitions`

Stores audit history of control-plane transitions:

- from status
- to status
- actor type
- actor id
- reason code/detail
- lease token

---

## Concurrency and lease model

### Claiming

Workers claim tasks with a PostgreSQL transaction using `FOR UPDATE SKIP LOCKED`.

A successful claim must atomically:

- change status to `in_progress`
- assign lease token and owner
- set lease expiration
- increment attempt count
- record transition history

### Lease renewal

Both `in_progress` and `verifying` tasks may renew leases.

If renewal fails, the worker must stop attempting terminal writes.

### Stale worker protection

Before any terminalization or state advancement, the repository must verify:

- the task still exists
- the status is expected
- the current lease token matches
- the lease has not expired
- the attempt number matches

If any of these checks fail, the repository rejects the write as stale.

---

## Execution and verification lifecycle

### Worker flow

1. Claim next ready task
2. Execute task under active lease
3. If execution succeeds, transition to `verifying`
4. Run verifier under active lease
5. Finalize to one of:
   - `done`
   - `failed`
   - `pending`
   - `blocked`
   - `awaiting_approval`

### Why verification is mandatory

Execution success only means the task produced output.

It does not prove that the output satisfies the task definition.

Therefore:

- execution result is necessary
- verification evidence is authoritative for completion

---

## Failure taxonomy

Failures are classified rather than treated uniformly.

### Retryable

Examples:

- `infra_failure`
- `timeout`
- retryable interruption
- temporary verifier runner failure

Default handling:

- write execution history
- clear lease
- return task to `pending`
- set `next_eligible_at`

### Non-retryable

Examples:

- `assertion_failure`
- `protocol_failure`
- policy or task-definition failures

Default handling:

- write execution history
- write verification evidence if present
- finalize to `failed`

### Policy-gated

Examples:

- approval required
- frozen path
- missing required human decision

Default handling:

- finalize to `blocked` or `awaiting_approval`

---

## Repository responsibilities

The repository is responsible for:

- claiming work atomically
- renewing leases
- enforcing current lease ownership
- recording execution history
- recording verification evidence
- recording approval events
- clearing or preserving retry metadata
- finalizing terminal or semi-terminal states transactionally

The repository is not responsible for:

- choosing verification commands
- interpreting task meaning
- selecting test frameworks
- deciding task-specific verification policy

---

## Worker service responsibilities

The worker service is responsible for:

- coordinating claim -> execute -> verify -> finalize
- passing heartbeat capability to execution and verification
- routing execution and verification results to the correct repository finalize path
- never writing direct task state outside repository APIs

The worker service is not responsible for:

- raw SQL
- task-specific verification rule selection
- using executor self-report as final authority

---

## Verifier responsibilities

A verifier is responsible for:

- selecting task-appropriate checks
- executing those checks
- returning structured verification evidence
- classifying its outcome as one of:
  - `passed`
  - `failed`
  - `retryable_failure`
  - `awaiting_approval`

A verifier is not responsible for:

- writing database state directly
- finalizing `done`
- bypassing repository correctness checks

---

## Approval model

Some tasks require human review even after automated checks pass.

Examples:

- UI or UX tasks
- product language changes
- governance or process changes
- risky operational tasks

For these tasks:

- automated verification may produce sufficient evidence
- the repository finalizes to `awaiting_approval`
- a human decision later transitions the task to `done` or `failed`

Approval decisions must be recorded as structured events.

The same rule applies one layer earlier for natural-language intake proposals: `natural_language_intent` persists `approved_at`, `approved_by`, `reviewed_at`, `reviewed_by`, `review_action`, and `review_feedback` so review decisions remain auditable before promotion into canonical tasks.

---

## Transaction rules

The following repository operations must be transactionally atomic.

### Claim

- select candidate
- update task to `in_progress`
- assign lease
- increment attempt
- write transition

### Finalize success

- assert lease ownership
- insert execution run
- insert verification evidence
- update `work_items` to `done`
- clear lease
- write transition

### Finalize failure, retry, and approval

- assert lease ownership
- insert execution run
- optionally insert verification evidence
- update task state
- clear lease
- write transition

Half-written terminal state is not acceptable.

---

## Testing strategy

Testing is organized into four layers.

### 1. Repository tests

Use real PostgreSQL where possible.

Focus on:

- claim concurrency
- lease renewal
- stale lease rejection
- atomic finalization
- retry writeback
- approval finalization

### 2. Worker service tests

Use mocked repository and fake executor/verifier.

Focus on:

- branching and routing
- transition to `verifying`
- correct finalize method selection
- lease-loss behavior

### 3. Verifier tests

Test verification strategy in isolation.

Focus on:

- command selection
- result classification
- evidence aggregation
- manual review detection

### 4. Integration smoke tests

Use real repository plus fake executor and verifier.

Focus on:

- `ready -> done`
- retry/backoff
- approval flow
- expired lease recovery

---

## Invariants

The system must preserve the following invariants:

1. A task in `done` has verifier-backed evidence or an approval event
2. A stale lease holder cannot finalize a task
3. A single task cannot be claimed by two active workers at once
4. Attempt numbers are monotonic
5. Terminal state changes are recorded in transition history
6. Retryable failures preserve attempt history
7. Verification is a formal lifecycle phase, not an external afterthought

---

## Implementation priorities

Recommended implementation order:

1. state model and repository interfaces
2. `claim_next_ready_work_item`
3. `renew_lease`
4. `transition_to_verifying`
5. `finalize_success`
6. `finalize_failed`
7. `finalize_retryable`
8. `finalize_awaiting_approval`
9. `record_approval_and_finalize`
10. worker service orchestration
11. verifier adapters
12. repository and service tests
13. integration smoke tests

---

## Summary

This design keeps orchestration correctness and task correctness separate but coherent:

- the **orchestrator** guarantees safe state transitions, concurrency control, retries, and authoritative finalization
- the **verifier** proves whether produced output satisfies task requirements
- the **approval path** handles tasks whose final correctness cannot be decided automatically

The most important failure mode to avoid is this:

> marking a task as complete without trustworthy completion evidence

That is why repository-owned terminalization plus verifier-backed terminal states is the core correctness rule for this orchestrator.
