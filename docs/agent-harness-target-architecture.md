# Taskplane Agent Harness Target Architecture

> 最后更新：2026-04-07
> 状态：proposed target architecture

本文档定义 Taskplane 对齐 harness engineering 的目标架构：

- 保留 PostgreSQL 控制面作为 runtime truth substrate
- 引入显式 agent loop 作为统一执行骨架
- 把 planning artifacts 做成 durable cognitive state
- 把 orchestrator session 升级为长周期 handoff 容器
- 将 EvalOps / CI gate 作为外置评估层，而不是污染 runtime truth

---

## 1. 一句话目标

Taskplane 的目标形态是：

> 以 PostgreSQL 为 runtime truth substrate，以显式 agent loop 为执行骨架，以 durable planning artifacts 为跨会话认知载体，以 orchestrator session 为长周期 handoff 容器，以 EvalOps 为外置评估与 CI 决策层。

---

## 2. 目标解决的问题

目标架构需要同时解决以下问题：

1. 统一系统级 agent loop
2. 让“计划”成为 durable artifact
3. 让 session 成为长周期任务容器
4. 把 verification 接入 loop，而不只是 terminal gate
5. 把 EvalOps 从理念变成真实系统边界

---

## 3. 六层目标架构

### Layer 1. Truth Substrate

职责：

- authoritative runtime facts
- state machine truth
- claim / lease / finalize
- execution run history
- verification evidence
- artifact references
- approval events
- wakeup / checkpoint / policy resolution

典型对象：

- `work_item`
- `work_dependency`
- `work_claim`
- `execution_run`
- `verification_evidence`
- `execution_session`
- `execution_checkpoint`
- `execution_wakeup`
- `artifact`
- `event_log`
- `approval_event`

原则：Taskplane 内核只对“发生了什么”负责，不对“效果好不好”做最终评分判断。

### Layer 2. Cognitive Harness Layer

职责：

- agent loop 的显式建模
- planning artifacts
- handoff state
- compact context
- replan / escalate 决策

这一层负责任务认知状态，而不是 executor、verifier 或 reporting UI。

### Layer 3. Orchestration Runtime Layer

职责：

- 驱动 loop 执行
- 调度 decomposition / story / task
- 管理并发和恢复
- 读取 cognitive artifacts 并执行当前动作
- 将结果写回 truth substrate 和 planning surface

### Layer 4. Execution & Verification Adapters

Execution 侧：

- codex / opencode / browser / script executor
- workspace / git worktree
- writeback / committer

Verification 侧：

- task verifier
- shell verifier
- structured verifier profiles
- approval-required determination

### Layer 5. Operator & Session Interface

职责：

- 查看目标 / 当前计划 / 当前 milestone
- 查看 blocked 原因与 open decisions
- 处理 clarification / review / approval / operator request
- 手动触发 replan / resume / abort / retry

### Layer 6. EvalOps / CI Layer

职责：

- regression
- benchmark suite
- behavior fingerprint
- run comparisons
- release gates
- dashboards / trend analysis

原则：读取 Taskplane runtime facts，但不反写 runtime truth。

---

## 4. 系统级 canonical agent loop

Taskplane 的系统级 loop 应明确为：

```text
Observe
  -> Plan
  -> Act
  -> Verify
  -> DecideNext
       -> Complete
       -> Continue
       -> Replan
       -> Escalate
       -> Suspend
```

### Observe

输入：

- 当前 `work/session/story/epic` 状态
- 最近 execution runs
- 最近 verification evidence
- 当前 plan artifact
- open decisions / operator requests
- budget / deadline / capacity / wave / guardrails

输出：`observation_snapshot`

### Plan

输入：

- observation snapshot
- objective
- current milestone
- previous plan
- failure / blocked evidence

输出：

- `plan_revision`
- `next_action`
- `success_criteria`
- `replan_reason`（如有）

### Act

输入：

- next action
- executor profile
- workspace context
- action contract

输出：

- `execution_run`
- `artifact refs`
- `act_result_summary`

### Verify

输入：

- action output
- verification profile
- expected success criteria

输出：

- `verification_evidence`
- `verification_summary`
- `verification_status`

### DecideNext

输出之一：

- complete
- continue
- replan
- escalate
- suspend

---

## 5. Planning Artifacts

建议引入以下 durable artifacts：

### Objective Artifact

- `objective_id`
- `scope_type`
- `objective_summary`
- `acceptance_contract`
- `constraints`
- `priority`
- `owner_kind`

### Plan Artifact

- `plan_id`
- `scope_type`
- `scope_ref`
- `plan_version`
- `status`
- `milestones_json`
- `next_action_json`
- `assumptions_json`
- `success_criteria_json`
- `supersedes_plan_id`

### Handoff Artifact

- `handoff_id`
- `session_id`
- `summary`
- `what_changed`
- `open_questions`
- `next_recommended_action`
- `linked_plan_id`

### Replan Event

- `replan_id`
- `trigger_type`
- `previous_plan_id`
- `new_plan_id`
- `reason_summary`
- `supporting_evidence_refs`

### Completion Contract

- `contract_id`
- `scope_type`
- `required_verification_profiles`
- `approval_required`
- `expected_artifacts`
- `done_definition`

最小落地版本可以先做：`objective`、`plan`、`handoff`。

---

## 6. Session / Handoff 模型

`orchestrator_session` 的目标形态不只是 watch 当前状态，而是围绕某个 objective 的长周期上下文容器。

### Session Header

- `session_id`
- `repo`
- `host_tool`
- `objective_summary`
- `started_by`
- `session_status`
- `current_phase`
- `current_plan_id`
- `current_milestone`

### Live State

- running jobs
- active stories/tasks
- current blockers
- pending operator requests
- pending approvals

### Compact Context

- last observation summary
- current plan summary
- recent execution summary
- recent verification summary
- open decisions
- next recommended actions

### Durable Handoff

- latest handoff artifact
- plan history
- replan history
- milestone progression

### Session 状态建议

- `active`
- `awaiting_operator`
- `suspended`
- `completed`
- `aborted`
- `failed`

`execution_session` 表示进程连续性；`orchestrator_session` 表示任务连续性。

---

## 7. Planner / Scheduler / Decomposer 边界

### Eligibility Planner

职责：谁 ready、谁被依赖或 blocker 卡住。

建议未来在术语上明确为 `eligibility_planner` 或 `ready_state_deriver`。

### Scheduler

职责：

- 谁先执行
- 并发如何分配
- 哪些 story / decomposition job 被启动
- 恢复什么，跳过什么

### Task Planner / Decomposer

职责：

- 根据 objective / story / epic 生成计划
- 维护 milestone
- 决定是否 replan
- 生成 next action
- 输出 handoff

### Verifier Planner（可选）

职责：

- task type -> verifier profile mapping
- 生成验证步骤
- 控制验证范围，避免 scope creep

---

## 8. Verification 目标形态

Verification 是 loop 的正式 phase，而不是附属步骤。

建议拆成三层：

### Runtime Verification

- shell verifier
- evidence persistence
- pass/fail classification

### Verification Policy

- task type -> verifier profile mapping
- allowed command scope
- required evidence schema
- approval gate rules

### Verification Summary

- what was checked
- what passed / failed
- what remains unverified
- whether next step is retry / replan / escalation

完成定义：

```text
task done =
  repository-owned finalization
  + completion contract satisfied
  + verification evidence sufficient
  + required approval satisfied
```

---

## 9. EvalOps 子系统

### Taskplane 回答

- 发生了什么？
- 当前真实状态是什么？
- 这次 attempt 是否 verifier-backed complete？
- 为什么 blocked / retry / awaiting approval？

### EvalOps 回答

- 这版系统比上一版更好吗？
- 哪类任务成功率变差了？
- 哪个 executor / profile / plan strategy 更优？
- 能否放行到 CI / release？

### EvalOps 输入

- `execution_run`
- `verification_evidence`
- `artifact refs`
- `plan artifacts`
- `replan events`
- `session summaries`
- `operator interventions`

### EvalOps 输出

- success rate by task type
- first-attempt success rate
- average attempts to completion
- verification failure categories
- replan frequency
- operator intervention rate
- session completion latency
- loop-phase failure distribution
- behavior fingerprint regression result

### CI gate 分层

1. Deterministic Kernel Gates
2. Scenario Regression Gates
3. Statistical / Behavior Gates

---

## 10. 推荐主链路

```text
1. Intake / Import
2. Governance / Promotion
3. Session Start
4. Observe
5. Plan
6. Schedule
7. Act
8. Verify
9. DecideNext
10. Handoff / Compact
11. Eval Export
```

---

## 11. 分阶段落地建议

### Phase 1：统一语义，不大改 runtime

- 定义 canonical agent loop
- 明确 planner / scheduler / decomposer 命名边界
- 给 `orchestrator_session` 增加 objective + plan summary + handoff summary
- 给 verification 增加 compact summary surface
- 补统一 runtime diagram / doc 入口

### Phase 2：引入 durable planning artifacts

- 新增 `objective`
- 新增 `plan`
- 新增 `handoff`
- 新增 `replan_event`
- story / epic / session 开始写 plan version 和 next action

### Phase 3：外置 EvalOps 与 CI gates

- 稳定 export surface
- curated scenario suite
- regression runner
- smoke tasks
- release thresholds
- dashboards / trend reports

---

## 12. 最终总结

当前 Taskplane 已经具备：

- 事实层
- 执行层
- 验证层
- 调度层

目标是在现有强事实层之上补出两块：

1. **Cognitive Harness**：loop / plan / handoff / replan
2. **EvalOps**：regression / benchmark / CI gate / trend analysis

这将把 Taskplane 从强 control plane / orchestration substrate，推进成完整的 agent engineering platform。
