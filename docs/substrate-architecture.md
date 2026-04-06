# AI Orchestration Substrate Architecture

## Positioning

This repository already contains two different layers:

1. **Reusable orchestration substrate**
2. **Stardrifter-specific reference adapters and governance policy**

The reusable layer is the part that should be preserved and generalized. The Stardrifter-specific layer should be treated as one concrete deployment of that substrate, not as the substrate itself.

This document explains that boundary.

For engineering enforcement boundaries (what must be rigid vs what should remain flexible), see:

- `docs/adr/0001-engineering-boundaries.md`

For the boundary between Taskplane's runtime fact kernel and any downstream EvalOps/reporting platform, see:

- `docs/eval-boundary.md`

---

## What the substrate is

The substrate is a PostgreSQL-backed execution control plane for AI or scripted work.

Its core responsibilities are:

- model work units and dependencies
- decide when work is runnable
- claim work safely under concurrency
- execute and verify work through adapters
- persist execution evidence
- manage retry, lease, and terminalization semantics
- coordinate durable closure before external writeback

In other words, the substrate is the **truth owner for orchestration state**, not the truth owner for the target application domain.

---

## Core substrate modules

These modules already behave like reusable orchestration infrastructure.

### Control-plane data model

- `src/taskplane/models.py`

Core reusable entities include:

- `WorkItem`
- `WorkDependency`
- `WorkTarget`
- `WorkClaim`
- `ExecutionRun`
- `VerificationEvidence`

These model the orchestration lifecycle independently of Stardrifter-specific gameplay or migration logic.

### Repository-backed control plane

- `src/taskplane/repository.py`
- `src/taskplane/factory.py`

This is the strongest reusable seam in the project.

It already owns:

- atomic claim
- claim-next selection
- lease renewal / expiry
- abandoned in-progress recovery
- retry/backoff persistence
- attempt finalization
- canonical commit linkage

The repository is the actual control-plane authority.

### Scheduling and safety core

- `src/taskplane/planner.py`
- `src/taskplane/guardrails.py`
- `src/taskplane/queue.py`

These modules implement generic orchestration logic:

- ready derivation
- execution guardrails
- path-conflict detection
- queue evaluation

They are not inherently coupled to GitHub, Stardrifter, or one specific issue taxonomy.

### Worker shell

- `src/taskplane/worker.py`

The worker is best understood as an orchestration shell around the repository.

Its substrate responsibilities are:

- evaluate candidates
- claim via repository
- prepare workspace if needed
- invoke executor/verifier adapters
- route outcomes to repository-owned finalization
- trigger external writeback only after DB closure

### Runtime adapters

- `src/taskplane/adapters.py`
- `src/taskplane/opencode_task_executor.py`
- `src/taskplane/workspace.py`
- `src/taskplane/git_committer.py`
- `src/taskplane/github_writeback.py`

These are already adapter-shaped, even if they are still packaged under the same namespace.

The project now also has explicit adapter-facing Protocols in:

- `src/taskplane/protocols.py`

Current formalized interfaces include:

- `ExecutorAdapter`
- `VerifierAdapter`
- `TaskWritebackAdapter`
- `StoryWritebackAdapter`
- `WorkspaceAdapter`
- `IntakeAdapter`
- `HierarchyRunnerAdapter`

They should be treated as pluggable runtime edges:

- executor adapter
- verifier adapter
- workspace adapter
- commit adapter
- external writeback adapter

---

## What is Stardrifter-specific today

These modules are valuable, but they are not substrate core. They encode one concrete source system, one governance model, and one domain workflow.

### GitHub issue intake and projection

- `src/taskplane/github_sync.py`
- `src/taskplane/github_importer.py`
- `src/taskplane/issue_projection.py`
- `src/taskplane/projection_sync.py`

These assume:

- GitHub Issues as intake source
- a specific label/body taxonomy
- issue-number-backed identity
- projection from GitHub issue structure into executable work

That is a **source adapter**, not the substrate.

### Governance and hierarchy policy

- `src/taskplane/governance_sync.py`
- `src/taskplane/governance_priority_cli.py`
- `src/taskplane/governance_report_cli.py`
- `docs/program-governance-model.md`

These encode one hierarchical policy layer:

- program epic
- program story
- lane / wave gating
- decomposition / activation policy

This is a **domain governance adapter**, not a universal orchestration requirement.

### Story decomposition and story runner semantics

- `src/taskplane/story_runner.py`
- `src/taskplane/story_runner_cli.py`
- `src/taskplane/story_decomposition.py`
- `src/taskplane/opencode_story_decomposer.py`

These are useful reference implementations of hierarchical execution, but they are one strategy for grouping work, not the substrate’s only valid execution model.

### NocoDB presentation layer

- `docs/nocodb-integration.md`
- `sql/nocodb_views.sql`

This is an observer/UI layer. It is not needed for the substrate to exist.

---

## Recommended boundary model

The project should be described in three layers.

```text
AI Orchestration Substrate
  ├─ control-plane schema
  ├─ repository contract and implementations
  ├─ queue/planner/guardrail logic
  ├─ worker lifecycle
  └─ adapter contracts

Reference Adapters
  ├─ GitHub source adapter
  ├─ shell/opencode executor adapter
  ├─ git commit adapter
  ├─ GitHub writeback adapter
  └─ workspace/worktree adapter

Stardrifter Deployment
  ├─ issue taxonomy and projection rules
  ├─ program epic/story governance
  ├─ story decomposition policy
  └─ NocoDB board/report views
```

This is the simplest mental model that matches the code as it actually exists.

---

## Generic contracts that already exist

The following seams are already real enough to document as reusable contracts.

### Intake adapter

Source system → normalized work graph.

Today’s implementation:

- GitHub issues → normalized staging → `work_item` / `work_dependency`

Generalized contract:

- produce work units
- produce dependency edges
- optionally produce hierarchy/grouping metadata

Code-level seam:

- `IntakeAdapter`

### Natural-language intake review adapter

Prompt → proposal → explicit review → canonical promotion.

Today’s implementation:

- CLI handles submit / answer / approve
- console / API handle approve / reject / revise review actions
- `natural_language_intent` stores proposal, clarification, and review metadata
- `story_task_draft` stores the task draft records produced during promotion

Generalized contract:

- accept a natural-language prompt
- produce a proposal that stays separate from canonical truth
- record explicit review decisions before promotion
- promote into canonical entities only through a durable boundary

Code-level seams:

- `NaturalLanguageIntakeService`
- `natural_language_intent`
- `story_task_draft`

### Executor adapter

`WorkItem` → `ExecutionResult`

Today’s implementations:

- shell executor
- opencode task executor

Generalized contract:

- deterministic terminal outcome
- structured failure classification
- optional heartbeat support
- optional changed-path metadata

Code-level seam:

- `ExecutorAdapter`

### Verifier adapter

`WorkItem` → `VerificationEvidence`

Today’s implementation:

- shell verifier

Code-level seam:

- `VerifierAdapter`

### Writeback adapter

terminal DB state → external status update

Today’s implementations:

- task-level GitHub writeback
- story-level GitHub closure

Code-level seams:

- `TaskWritebackAdapter`
- `StoryWritebackAdapter`

### Workspace adapter

claimed work → isolated filesystem context

Today’s implementation:

- git worktree-backed workspace manager

Code-level seam:

- `WorkspaceAdapter`

---

## What should stay stable if this becomes a general substrate

These should be preserved as the platform core:

- PostgreSQL-backed control plane
- repository-owned claim and finalization
- worker as orchestration shell
- execution evidence and verification evidence model
- retry/lease/recovery semantics
- adapter-oriented execution boundary

These are the parts most worth stabilizing and documenting first.

---

## What should become explicitly adapter-owned

These should be documented as replaceable specializations:

- GitHub issue import and normalization
- Stardrifter issue/body conventions
- natural-language intake and review policy
- epic/story governance semantics
- story decomposition workflow
- NocoDB observer views

The project does not need to delete these. It just needs to stop presenting them as the architecture itself.

---

## Minimum path to a reusable substrate

The cheapest credible path is documentation-first, not a massive package split.

### Stage 1 — clarify boundaries in docs

- present the repo as substrate + adapters + reference deployment
- explain core contracts explicitly
- move Stardrifter-specific concepts out of the “core” narrative

### Stage 2 — formalize adapter contracts

- document intake/executor/verifier/writeback/workspace contracts
- optionally add Protocols later if needed

### Stage 3 — reduce naming coupling

- treat `program story`, `program epic`, `lane`, and `wave` as one reference governance model
- avoid describing them as universal substrate concepts

### Stage 4 — extract or rename only when necessary

- package split is optional at first
- do it only when a second deployment or a second source adapter actually appears

---

## Practical recommendation

If this repo is going to be used as a general AI orchestration base, the next highest-value move is not another deep code refactor.

It is to make the documentation and architecture boundaries explicit enough that:

- a second intake source could be imagined
- a second governance model could be plugged in
- a second executor stack could be adopted
- the existing Stardrifter flow still works unchanged as the first reference deployment

That is the shortest path from “project-specific orchestrator” to “reusable orchestration substrate.”
