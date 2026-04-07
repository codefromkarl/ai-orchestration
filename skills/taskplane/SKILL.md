# Skill: taskplane

Use Taskplane as the control plane for long-running engineering work.

## When to use

Use this skill when:
- starting a substantial coding task
- resuming interrupted work
- deciding whether to continue, verify, replan, or escalate
- checking current orchestration/session state
- evaluating smoke/threshold results
- needing stable suite/threshold metadata for CI or EvalOps

## Core principle

Taskplane is the control plane.
Codex is the executor.

Do not rely only on local intuition about task status when Taskplane session state is available.

## Standard workflow

### 1. Inspect current state first

Before substantial work, run:

- `/tp-watch`

Read and use:
- `current phase`
- `decision`
- `decision reason`
- `requires operator`
- `plan summary`
- `handoff summary`

If available, also interpret:
- `next_action`
- `milestones`
- `completion_contract`

### 2. Respect Taskplane decision state

If Taskplane indicates:

- `decision = verify`
  - do not continue arbitrary implementation work
  - inspect verification-related context first

- `decision = replan`
  - do not continue execution as if the previous plan still holds
  - revise or refresh planning state

- `decision = escalate`
  - do not continue automatic execution
  - surface operator-required context

- `decision = plan`
  - prioritize planning/decomposition/intake resolution work

- `decision = continue`
  - proceed with the next concrete action

### 3. Use Taskplane evaluation surfaces before claiming success

When checking current quality or CI readiness, run:

- `/tp-eval`
- `/tp-report`

Prefer machine-readable output where needed.

### 4. Use contract discovery when suite/threshold meaning matters

If suite/scenario or threshold semantics are needed, run:

- `/tp-contract smoke-suite`
- `/tp-contract threshold-profile`

## Recommended command mapping

- `/tp-watch` → inspect current orchestration/session state
- `/tp-report` → inspect attempt report
- `/tp-eval` → run default threshold evaluation
- `/tp-contract` → export eval contract JSON
- `/tp-supervise` → drive supervisor/orchestration command

## Guardrails

- Do not assume “done” only because code was changed.
- If Taskplane indicates `verify`, `replan`, or `escalate`, do not ignore it.
- Prefer Taskplane session state over ad hoc memory for multi-step work.
- Use Taskplane contracts instead of inventing ad hoc smoke suite or threshold names.

## Minimal decision policy

- Start with `/tp-watch`
- If `decision=continue`, proceed
- If `decision=verify`, inspect or run verification-related work
- If `decision=replan`, update plan/replan state before further execution
- If `decision=escalate`, stop autonomous progress and surface operator need
- If `decision=plan`, do planning/decomposition/intake work first
