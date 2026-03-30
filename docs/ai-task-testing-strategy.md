# AI Task Development Testing Strategy

## Purpose

When AI is used to execute development tasks, the goal is **not** to test whether the model “looks smart.”

The goal is to test whether the orchestration system can:

- supply a task in a controlled way
- classify AI outcomes reliably
- verify results deterministically
- recover from interruption or ambiguity
- measure actual success rate over repeated attempts

This document describes how to test that stack in this repository.

---

## Core principle

Treat AI as an **unreliable executor behind a strict protocol**, not as a trusted engineer.

That means:

- the AI’s structured output must be validated
- the worker state machine must be tested independently of model quality
- success must be defined by verifier-backed terminal states, not by model self-report
- attempt metrics must be observable from the control plane

---

## The four testing layers

### 1. Protocol-layer tests

These tests verify that executor output can be consumed safely.

In this repository, that means testing:

- structured JSON extraction
- terminal outcomes (`done`, `blocked`, `needs_decision`, `already_satisfied`)
- timeout classification
- paused / ask-next-step normalization
- non-terminal payload rejection
- nonzero exit classification (`interrupted_retryable`, `tooling_error`, etc.)

Current examples:

- `tests/test_opencode_task_executor.py`

What this layer answers:

> Can the orchestration system trust the executor output format enough to drive state transitions?

This layer should remain mostly deterministic and fast.

---

### 2. Orchestrator state-machine tests

These tests verify that once the executor returns an outcome, the worker and repository perform the correct lifecycle transitions.

In this repository, that includes testing:

- claim / lease behavior
- retry and backoff transitions
- `needs_decision` handling
- prepare-failure rollback
- heartbeat-driven lease renewal
- repository-owned attempt finalization
- task and story GitHub writeback
- commit / PR linkage recording

Current examples:

- `tests/test_worker.py`
- `tests/test_repository.py`
- `tests/test_story_runner.py`

What this layer answers:

> Given a classified executor outcome, does the orchestration control plane do the right thing?

This is the most important layer in the project.

---

### 3. Verification-layer tests

These tests ensure that “successful execution” actually means “verified result,” not merely “command finished.”

For AI-driven development, verifier tests should be tailored to task type:

- code tasks → unit test / typecheck / targeted integration verification
- document tasks → structure/lint/link validation
- CLI tasks → output and exit-code validation
- schema tasks → migration/query sanity checks

Current examples:

- shell verifier flows in `tests/test_adapters.py`
- verification evidence assertions in `tests/test_worker.py`

What this layer answers:

> Can the system distinguish AI output that merely exists from output that is actually valid?

This is where true success rate should be anchored.

---

### 4. Limited live-AI smoke tests

This is the thinnest layer and should remain intentionally small.

Use it only for a few critical end-to-end chains, such as:

- one small code task
- one small documentation task
- one `needs_decision` task
- one retryable timeout/interruption path

Live AI tests are valuable, but they are:

- slower
- more expensive
- less deterministic
- harder to debug when they fail

So they should validate the integration boundary, not replace deterministic tests.

What this layer answers:

> Does the full runtime chain behave plausibly when a real model is in the loop?

---

## What not to use as a success signal

Do **not** treat these as proof of success:

- the AI said “done”
- the generated diff looks reasonable
- the command exited 0
- one manual run succeeded once

In this repository, the trustworthy success signal is:

> repository-owned terminalization + verifier-backed terminal state + observable attempt record

---

## How to define success rate in this project

For AI-driven task development, success rate should be measured from the control plane, not from anecdotes.

Useful metrics include:

- total attempts
- first-attempt success rate
- eventual success rate
- average attempts to success
- timeout rate
- `needs_decision` rate
- protocol/tooling error rate
- verification failure rate

The repository already persists the raw ingredients for this:

- `ExecutionRun`
- `VerificationEvidence`
- `attempt_count`
- `last_failure_reason`
- `next_eligible_at`

The first reporting helper now exists in:

- `src/stardrifter_orchestration_mvp/attempt_report.py`

This should be treated as the starting point for success-rate observability, not the final form.

---

## Recommended test distribution

For this project, a healthy split looks like:

- **Most tests**: deterministic protocol + orchestrator + verification tests
- **A few tests**: integration tests against real PostgreSQL claim/reconciliation behavior
- **Very few tests**: live-AI smoke tests

That distribution gives the best balance between confidence, speed, and cost.

---

## Current repository mapping

### Protocol tests

- `tests/test_opencode_task_executor.py`

### Orchestrator tests

- `tests/test_worker.py`
- `tests/test_repository.py`
- `tests/test_story_runner.py`

### Adapter and verifier tests

- `tests/test_adapters.py`
- `tests/test_git_committer.py`
- `tests/test_github_writeback.py`

### External closure / reconciliation tests

- `tests/test_reconciliation.py`

### Real PostgreSQL integration tests

- selected `tests/test_repository.py` cases gated by `STARDRIFTER_TEST_POSTGRES_DSN`

---

## Near-term gaps in the testing strategy

Even after the current reliability work, a few testing gaps remain.

### 1. More detailed executor taxonomy coverage

Still worth adding tests for:

- malformed but partially structured payloads
- interrupted subprocess classes beyond timeout
- protocol/tooling error split across more cases

### 2. Attempt reporting CLI and richer metrics

The project has a basic attempt report builder, but not yet a dedicated CLI/reporting surface for success-rate tracking.

### 3. Live-AI smoke test layer

There is not yet a small, intentionally curated smoke-test set for real executor runs.

### 4. Repair-vs-report testing boundaries

The reconciliation layer now has:

- read-only drift detection
- safe auto-repair for task/story status drift

But the project still needs explicit tests for where auto-repair must stop, especially around PR linkage.

---

## Practical recommendation

When adding new AI-driven features in this repository, use this order:

1. **Protocol test first** — can the result be consumed safely?
2. **Worker/repository test second** — does the control plane react correctly?
3. **Verifier test third** — how is correctness validated?
4. **Optional live smoke test last** — does the end-to-end chain behave plausibly with a real model?

If a proposed feature cannot be tested at those layers, the feature contract is probably still too vague.

---

## Bottom line

The right way to test AI task development is not to ask whether the model “did a good job.”

The right question is:

> Can the orchestration system reliably convert AI output into a verifier-backed, observable, recoverable terminal state?

That is the testing model this repository should continue to optimize for.
