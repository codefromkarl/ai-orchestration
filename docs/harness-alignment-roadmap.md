# Taskplane Harness Alignment Roadmap

**状态**: Draft  
**最后更新**: 2026-04-07  
**适用范围**: Taskplane orchestration / session runtime / verification / EvalOps boundary

---

## 1. 背景

Taskplane 当前已经完成以下基础工作：

### 已完成能力
1. **Phase 1: Canonical loop session surface**
   - `orchestrator_session` watch surface 暴露 `current_phase`
   - 暴露 canonical loop
   - 暴露 compact session summary

2. **Phase 2: Durable session planning summaries**
   - `orchestrator_session` 已持久化：
     - `current_phase`
     - `objective_summary`
     - `plan_summary`
     - `handoff_summary`

3. **Phase 3: Minimal EvalOps-facing report surface**
   - `attempt_report` 输出 versioned fact summary
   - `taskplane-attempt-report` 支持 JSON 输出
   - 形成最小 CI / EvalOps 消费入口

这些工作解决了：
- 统一 loop 语言
- 建立最小 durable planning surface
- 建立最小 machine-readable report/export surface

---

## 2. 当前阶段判断

Taskplane 目前处于：

> **从“架构语义对齐”进入“runtime harness 产品化”的阶段。**

当前系统已经不缺：
- control plane substrate
- repository truth ownership
- verifier-backed completion
- basic session/watch/report surfaces

当前系统仍然缺：
- structured planning artifacts
- loop-driven runtime transitions
- regression-ready EvalOps substrate

---

## 3. Roadmap 目标

后续 roadmap 的目标不是继续增加零散字段，而是完成三个收敛：

1. **Planning 收敛**
   - 从 summary strings 演进到 structured planning artifacts

2. **Loop 收敛**
   - 从“展示 canonical loop”演进到“runtime 真正按 loop 驱动”

3. **EvalOps 收敛**
   - 从“有 JSON summary”演进到“可以支撑 regression / CI gate”

---

## 4. 设计原则

### 4.1 保持 Taskplane / EvalOps 边界
Taskplane 继续负责：
- runtime facts
- state transitions
- execution / verification evidence
- approval / retry / finalize semantics

EvalOps 负责：
- benchmarking
- regression comparison
- scoring / ranking
- release gating
- long-horizon analytics

### 4.2 优先补结构，不优先补展示
优先做：
- durable structured state
- stable contracts
- machine-consumable surfaces

而不是优先做：
- dashboard
- rich visualization
- derived scoring inside control plane

### 4.3 优先让 loop 成为控制骨架
canonical loop 不应停留在 session 文本层。  
后续应逐步成为：
- planning trigger
- scheduler input
- verifier transition driver
- escalation / replan policy entrypoint

### 4.4 长任务恢复必须依赖工件，不依赖“重新理解日志”
长时任务恢复依赖：
- objective
- plan
- milestone
- next action
- handoff
- replan reason

而不是依赖：
- 重新读大量原始日志
- 重新猜测执行策略

---

## 5. Roadmap 总览

后续 roadmap 分为三条主线：

### Track A. Structured Planning Artifacts
目标：
- 把 planning surface 从 string summary 升级为结构化 durable artifacts

### Track B. Loop-Driven Runtime
目标：
- 让 canonical loop 成为 runtime 真正执行的骨架

### Track C. EvalOps / CI Productization
目标：
- 让 versioned report/export surface 能支撑 regression 和 CI

---

# Track A. Structured Planning Artifacts

## A.1 目标

建立最小但可演进的 planning model，让 session 不只是展示摘要，而是具备真正的任务认知状态。

## A.2 为什么优先做
这是后续所有工作的基础：

- 没有 structured plan，loop 无法真正驱动 runtime
- 没有 milestone / next_action，session 无法成为真正 handoff container
- 没有 replan chain，EvalOps 无法分析 planning quality

## A.3 范围

### A1. Structured `next_action`
新增结构化 `next_action` 持久化，至少包含：

- `action_kind`
- `target_scope`
- `rationale`
- `expected_output`
- `verifier_hint`

### A2. `milestone` model
新增 milestone 概念，至少包含：

- `milestone_id`
- `summary`
- `status`
- `completion_criteria`
- `ordering`

### A3. `plan_version`
新增 plan versioning 能力，至少包含：

- `plan_version`
- `supersedes_plan_id`
- `active / superseded / completed / abandoned`

### A4. `replan_event`
新增 replan first-class event，至少包含：

- `trigger_type`
- `reason_summary`
- `supporting_evidence_refs`
- `previous_plan_id`
- `new_plan_id`

### A5. `completion_contract`
新增 completion contract snapshot，至少包含：

- `required_verification_profiles`
- `required_evidence_classes`
- `approval_required`
- `expected_artifacts`

## A.4 完成标准

Track A 完成时，应满足：

- session 可以持久化结构化 `next_action`
- session 或关联对象可以持久化 milestone progression
- 系统可以记录 plan revision chain
- replan 不再只是隐式效果，而是显式事件
- planning 和 verification 之间存在 contract linkage

## A.5 风险
主要风险：

- schema 扩展过快
- plan 结构设计过重，影响现有 runtime
- 把 planning artifacts 做成 UI 文本，而不是 machine-consumable state

### 风险控制
- 先做最小字段
- 先让 session 使用，再决定是否拆独立表
- 所有 planning state 必须明确 consumer

---

# Track B. Loop-Driven Runtime

## B.1 目标

让 canonical loop 从“显示层语义”升级成“系统级执行骨架”。

## B.2 为什么现在还不够
当前已有：
- `current_phase`
- canonical loop
- compact summary

但这些还主要用于：
- session watch
- operator 理解
- runtime 摘要

还没有真正用于：
- phase-aware scheduling
- verify-driven transitions
- explicit replan control
- bounded loop iteration

## B.3 范围

### B1. 定义 canonical phase transition rules
明确每个 phase 的：

- 输入
- 输出
- 允许迁移
- terminal conditions

最小 transition 集合：

- observe -> plan
- plan -> act
- act -> verify
- verify -> decide_next
- decide_next -> complete / continue / replan / escalate / suspend

### B2. Scheduler / Supervisor 感知 phase
让 scheduling 不只是看：
- ready
- capacity
- worker slots

而是也看：
- current_phase
- whether replan is required
- whether verify must happen before more act

### B3. `verify -> decide_next` 正式化
把 verify 结果变成明确 transition 输入：

- verified complete
- partial progress
- verification failed
- blocked / approval pending
- no progress
- retryable tooling failure

### B4. Replan / Escalate 成为显式 runtime transition
不是仅靠 recommended actions 表达，而是控制面正式记录：

- why loop did not continue
- why session changed course
- whether operator input is required

### B5. Compact context refresh contract
每轮 loop 结束都生成 compact handoff，至少包含：

- what changed
- what passed/failed
- what remains
- next action
- whether operator input is required

## B.4 完成标准

Track B 完成时，应满足：

- `current_phase` 不只是展示字段，而参与 runtime decisions
- verify 结果能正式驱动 next-step transition
- replan / escalate / suspend 有正式状态语义
- session handoff 在每轮 loop 后稳定刷新
- operator 能看到“为什么进入这一 phase”，而不只是看到状态变化

## B.5 风险
主要风险：

- 把 scheduler 和 planner 耦合过紧
- phase 设计过细导致系统过度复杂
- runtime 控制和展示层混在一起

### 风险控制
- 先定义最小 phase machine
- scheduler 只消费 phase signal，不拥有 plan semantics
- plan / phase / summary 各自职责清晰

---

# Track C. EvalOps / CI Productization

## C.1 目标

把当前 versioned attempt report 升级为真正可用于 regression / CI 的事实输入层。

## C.2 为什么当前还不够
当前已有：
- versioned attempt report
- JSON output
- existing eval export endpoints

但还缺：
- scenario identity
- stable grouping / suite semantics
- threshold rules
- failure rollups
- curated smoke coverage

## C.3 范围

### C1. Scenario / Suite grouping
为 report/export 引入最小 grouping 维度，例如：

- `scenario_id`
- `suite_name`
- `repo`
- `executor_profile`
- `verifier_profile`

### C2. Failure taxonomy rollup
把现有 failure classes 收敛为稳定 taxonomy，例如：

- timeout
- protocol_error
- invalid_payload
- verifier_failed
- blocked_waiting_operator
- no_progress
- approval_pending
- tooling_error

### C3. Curated smoke suite
建立最小 smoke scenario 集合，建议至少覆盖：

1. first-attempt success
2. retry then success
3. blocked then escalate
4. verify fail then replan

### C4. Minimal CI gates
定义最小 CI release rules，例如：

- smoke suite pass rate 不低于阈值
- protocol_error 不回归
- average_attempts_to_success 不恶化
- first_attempt_success 不显著下降

### C5. Export / report schema documentation
文档化：
- schema versioning policy
- required fields
- stability guarantees
- consumer expectations

## C.4 完成标准

Track C 完成时，应满足：

- machine-readable report 可以稳定被 CI 消费
- smoke scenarios 有固定集合和可重跑入口
- 基本 regression 阈值已定义
- fact export 和 downstream judgment 仍然清晰分层
- 不把 derived evaluation fields 写回核心 control-plane tables

## C.5 风险
主要风险：

- 过早做复杂 benchmark orchestration
- 把 analytics 逻辑塞回 Taskplane runtime
- 让 EvalOps 反向污染 control-plane schema

### 风险控制
- 先 smoke，后 benchmark
- 先事实合同，后评分体系
- 明确只输出 facts，不输出 derived judgments

---

## 6. 推荐执行顺序

## Priority 1 — Track A
先做 Structured Planning Artifacts。

原因：
- 是 loop runtime 和 EvalOps 的共同前提
- structured plan 是当前最大缺口

## Priority 2 — Track B
再做 Loop-Driven Runtime。

原因：
- loop 只有在有结构化 planning state 时才适合真正驱动 runtime

## Priority 3 — Track C
最后做 EvalOps / CI Productization。

原因：
- EvalOps 最适合建立在稳定的 planning facts 和 loop semantics 之上

---

## 7. 对应 backlog 建议

### Epic 1: Durable Planning Model
- Story 1.1: persist structured next_action
- Story 1.2: persist milestone state
- Story 1.3: add plan version chain
- Story 1.4: add replan event records
- Story 1.5: add completion contract snapshot

### Epic 2: Loop Runtime Integration
- Story 2.1: define canonical phase transition policy
- Story 2.2: make scheduler phase-aware
- Story 2.3: formalize verify -> decide_next
- Story 2.4: add explicit replan / escalate transitions
- Story 2.5: refresh compact handoff after each loop

### Epic 3: EvalOps / CI Surface
- Story 3.1: add scenario/suite grouping to reports
- Story 3.2: standardize failure taxonomy rollups
- Story 3.3: build curated smoke suite
- Story 3.4: define CI thresholds
- Story 3.5: document export/report schema stability

---

## 8. 明确不优先做的事项

以下事项当前不建议优先：

### 8.1 大而全 dashboard
原因：
- 事实合同尚未完全稳定

### 8.2 复杂 benchmark orchestration
原因：
- 当前更缺 stable grouping 和 comparison contracts

### 8.3 多模型 comparative scoring
原因：
- 太容易混淆 runtime facts 与 evaluation judgments

### 8.4 在核心表中增加大量派生评估字段
原因：
- 违反 eval boundary 原则

---

## 9. 下一步建议

如果只选一个最值得立即开始的方向：

> **优先启动 Track A：Structured Planning Artifacts，先做 `next_action` 和 `milestone`。**

这是当前杠杆最大的点，因为它会同时改善：

- planning durability
- session handoff
- loop runtime integration
- future EvalOps comparability

---

## 10. 成功标志

当 roadmap 走完关键路径后，Taskplane 应该达到：

- session 不只是显示状态，而是承载 durable cognitive state
- canonical loop 不只是展示语义，而是 runtime 真正遵循的控制骨架
- report/export 不只是摘要，而是 regression / CI 可稳定消费的事实层
- EvalOps 与 Taskplane 的边界保持清晰，不混淆 truth 和 judgment
