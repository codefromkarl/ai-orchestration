# ADR 0001: Engineering Boundaries for the Orchestrator

## Status

Accepted

## Context

The orchestration system has now progressed beyond an early MVP and has accumulated a mixture of:

- durable control-plane semantics,
- operator-assisted workflow patches,
- decomposition fallback behavior,
- story completion/integration hardening,
- branch/worktree reconciliation,
- task execution and verification recovery logic.

During execution of real Story chains, the team repeatedly saw the same pattern:

1. some layers benefit from strict, mechanical enforcement,
2. some layers degrade badly if they are made overly rigid,
3. architectural instability comes mostly from weakly enforced closure boundaries,
4. implementation quality drops when creative/problem-solving layers are over-constrained.

We need a durable rule set for where the orchestrator must be strict and where it should preserve flexibility.

## Decision

We divide the system into **strong-constraint layers** and **flexibility-preserving layers**.

### Strong-constraint layers

These layers MUST be explicit, durable, and machine-verifiable.

#### 1. Control-plane state machine

The repository-backed control plane is the only source of truth for:

- `program_epic.execution_status`
- `program_story.execution_status`
- `work_item.status`
- `work_claim`
- `execution_run`
- `verification_evidence`
- `story_integration_run`
- `story_pull_request_link`
- `story_task_draft`
- `approval_event`

GitHub issues, PRs, labels, and operator observations are input signals, not final truth.

#### 2. Verification execution

Verification commands and allowed test scope must be structured and enforced. The verifier must not freely expand verification beyond the task contract.

Scope-external failures must not be mixed with implementation failures.

#### 3. Blocked-task recovery

Blocked tasks must only be restored through explicit, auditable recovery paths. Manual state changes without a recorded repair/requeue reason are not acceptable as standard workflow.

#### 4. Workspace and branch truth

Canonical story branches and worktrees define the valid closure boundary for Story integration. Their existence and drift status must be machine-checkable and reportable.

#### 5. Promotion / closure boundaries

The system must distinguish between:

- AI-produced draft task specs,
- promoted GitHub task issues,
- projected control-plane work items,
- story-level integration state,
- story-level PR state,
- post-verification approval state.

Each promotion boundary must be durable and auditable.

Natural-language intake proposals follow the same rule: review metadata stays in `natural_language_intent`, and promotion into canonical entities must be explicit rather than implied by UI state, comments, or downstream side effects.

#### 6. Approval state

Approval must be represented as an explicit state (`awaiting_approval`) and explicit events (`approval_event`). It must never be represented only as a generic blocked state or implied by PR review status.

### Flexibility-preserving layers

These layers should remain adaptable and allow engineering judgment.

#### 1. Story decomposition creativity

LLM-driven decomposition should be allowed to propose task shapes and cuts. The system should constrain outputs at the promotion boundary, not eliminate creativity at the generation boundary.

#### 2. Implementation detail choices

Within allowed paths and task boundaries, agents and engineers may choose the implementation structure, local refactors, and low-risk cleanup required to deliver correct code.

#### 3. Fallback wording and task phrasing

Fallback task generation should be policy-driven and lane-aware, but still evolvable. Wording and template detail should remain adjustable without changing core orchestration flow.

#### 4. Report presentation

Reason codes and structured state are strict. Their human-facing presentation in CLI/report output may evolve for readability.

## Consequences

### Positive

- more predictable orchestration behavior,
- cleaner triage and reconciliation,
- stronger auditability,
- fewer cases where operators must infer truth from text summaries,
- safer automation of decomposition, completion, and approval.

### Negative

- task authoring and decomposition promotion become more rigid,
- some operator workflows become slower,
- more cases surface as explicit blocked/refinement states instead of being silently pushed forward,
- opportunistic cross-scope fixes become harder unless task scope is updated formally.

## Operational Rules

1. If a task is blocked, its recovery path must be explicit and recorded.
2. If a Story has terminal tasks but is not done, closure must be attempted by a completion-aware orchestrator path, not by ad-hoc state edits.
3. If decomposition yields zero projectable tasks, the system must move through validation/retry/fallback/refinement semantics, not directly to opaque failure.
4. If branch/worktree drift exists, reconciliation must surface it before integration runtime is attempted.
5. If approval is required, it must enter `awaiting_approval` and produce an `approval_event`.

## Related Documents

- `docs/substrate-architecture.md`
- `docs/task-orchestrator-correctness-and-verification-design.md`
- `docs/eval-boundary.md`
- `docs/mvp-design.md`
