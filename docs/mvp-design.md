# Taskplane

## 目标

为远行星号迁移提供一套独立于 runtime truth 的任务编排控制面：

- Python runtime 继续是游戏世界 truth owner
- PostgreSQL 只负责任务、依赖、执行证据、PR 链接
- NocoDB 只做人类查看与少量手工修正
- GitHub 继续承担 PR review 和 merge

## MVP 范围

本版只解决 4 个问题：

1. 任务与依赖建模
2. `ready` 任务计算
3. lane / wave / freeze / owner / approval guardrails
4. 执行与验证证据沉淀

## 非目标

- 不在 MVP 中重写 runtime truth
- 不把 GitHub Issue 作为主状态机
- 不上 pgvector
- 不做自动拆 Story / Epic
- 不做 task 级自动 merge；当前集成边界收敛到 story 级 merge

## 最小架构

```text
PostgreSQL
  ├─ work_item
  ├─ work_dependency
  ├─ work_target
  ├─ execution_run
  ├─ verification_evidence
  └─ pull_request_link

Python Worker
  ├─ planner: 算 ready task
  ├─ guardrails: 校验 freeze/owner/wave/approval
  ├─ executor: 调用 codex/opencode/脚本
  ├─ verifier: 跑 pytest/lint/tsc
  └─ reporter: 回写执行结果

NocoDB
  ├─ Task Board
  ├─ Blocked Queue
  └─ Verification / PR
```

## 当前实现状态

已经落地：

- 控制面 PostgreSQL schema
- `ready` 计算
- guardrails 判定
- 队列评估
- 最小 worker cycle
- PostgreSQL repository 工厂入口
- CLI worker 入口
- shell executor / verifier 适配器
- richer execution / verification evidence（exit code / elapsed ms / stdout/stderr digest）
- GitHub task -> work_item projection
- story-level task draining runner
- story-level shared worktree / branch
- story 完成后自动 merge 回基线分支
- NocoDB 集成配置与只读视图

尚未落地：

- PR 自动创建
- PR 自动回写与更完整的 merge 策略

## 状态机

- `pending`
- `ready`
- `in_progress`
- `verifying`
- `blocked`
- `done`

## Guardrails

执行前必须拦截：

- 当前 task 不在允许 wave
- target 落在冻结前缀
- target 的 owner lane 与 task lane 不匹配
- target 需要人工审批

## 本轮落地内容

- `sql/control_plane_schema.sql`
- `src/taskplane/planner.py`
- `src/taskplane/guardrails.py`
- `tests/test_planner.py`
- `tests/test_guardrails.py`

## Repository-centric claim safety

### 解决的问题

MVP 初版的 worker flow 中，`queue.py` 负责算出 executable task，worker 再自己选 `executable_ids[0]`，然后调用 repository 做状态切换。

这个边界有两个问题：

1. worker 自己“拍板”选择第一个可执行 task，repository 只负责后续 claim，容易形成 read/claim 之间的竞态窗口。
2. `work_claim` 一度更接近 workspace 生命周期的一部分，而不是控制面 claim 边界的一部分，导致路径冲突检查更像 advisory check，而不是 authoritative claim gate。

本轮改造的目标不是把全部调度逻辑搬进 PostgreSQL，而是把**最终 claim 决策**收口到 repository，使 worker 负责算候选，repository 负责安全 claim。

### 改造后的 claim flow

当前单次 worker cycle 的关键顺序是：

1. `repository.sync_ready_states()` 同步 `pending/ready`
2. worker 读取 `work_items / dependencies / targets / active_claims`
3. worker 调用 `evaluate_work_queue(...)` 计算 `QueueEvaluation`
4. worker materialize blocked items
5. 如果存在 workspace manager，worker 为 executable candidates 预先计算 `workspace_path / branch_name`
6. worker 调用 `repository.claim_next_executable_work_item(...)`
7. repository 按 `evaluation.executable_ids` 顺序尝试 authoritative claim
8. claim 成功后，worker 才调用 `workspace_manager.prepare(...)`
9. 执行、验证、落状态、记录 evidence
10. `workspace_manager.release(...)` 删除 claim，并按配置决定是否清理 worktree

也就是说，worker 不再直接选择某个 executable id 然后 claim；worker 只负责生成候选集合，repository 才是最终的 claim owner。

### Repository 的职责

当前 `src/taskplane/repository.py` 中有两个关键 claim API：

- `claim_ready_work_item(...)`
- `claim_next_executable_work_item(...)`

其中：

- `claim_ready_work_item(...)` 是**原子 claim primitive**
- `claim_next_executable_work_item(...)` 是**按 executable 顺序尝试 claim 的 repository-owned selection boundary**

两者都接受同一组 claim metadata：

- `worker_name`
- `workspace_path`
- `branch_name`
- `lease_token`
- `lease_expires_at`
- `claimed_paths`

这意味着 claim 不再只是 `ready -> in_progress` 的状态翻转，而是伴随明确的工作空间与路径占用信息一起进入控制面。

### In-memory repository 的语义

`InMemoryControlPlaneRepository` 现在不再只是最小 stub，它也承担并发语义替身的作用。

当前行为：

- 使用 `_claim_lock: threading.RLock` 串行化 claim 边界
- 在 `claim_ready_work_item(...)` 内部同时完成：
  - `status == "ready"` 检查
  - 与已有 `work_claims` 的路径冲突检查
  - `in_progress` 状态切换
  - `WorkClaim` upsert
- `claim_next_executable_work_item(...)` 在同一锁边界内，按 executable 顺序委托到 `claim_ready_work_item(...)`

这里使用 `RLock` 而不是普通 `Lock`，是因为 `claim_next_executable_work_item(...)` 需要在持锁状态下继续调用 `claim_ready_work_item(...)`，既保住线程安全，也保住 fallback 语义。

### PostgreSQL repository 的语义

`PostgresControlPlaneRepository.claim_ready_work_item(...)` 现在承担真正的数据库 claim gate。

它在一次 SQL 里完成：

1. 用 `FOR UPDATE SKIP LOCKED` 锁定目标 `work_item`
2. 用 `work_claim` + `jsonb_array_elements_text(...)` 检查 `claimed_paths` 是否与现有 active claim 冲突
3. 将 `work_item.status` 更新为 `in_progress`
4. 生成 lease metadata 并 upsert `work_claim`

当前 `work_claim` 除了记录谁拿到了任务，也开始承担最小 lease 语义：claim 写入时会附带 `lease_token` 与 `lease_expires_at`。queue 评估和 repository claim recheck 现在都只把**未过期 claim**视为 active claim，worker 在 workspace prepare 成功后会做一次 lease renewal，支持 heartbeat 的 executor 还可以在长任务执行期间继续续租。`sync_ready_states()` 还会把“`in_progress` 但已经没有 active claim”的 abandoned work 自动降回可调度状态。如果 workspace prepare 本身失败，worker 会立即删除 claim 并把状态回退到可调度态。它仍然不是完整的 heartbeat 系统，但已经把 stale claim recovery 从“字段存在”推进到了实际调度语义。

这里的目标不是把全部 queue logic SQL 化，而是把**最终能不能 claim 成功**的判断放在数据库事务边界里。

`claim_next_executable_work_item(...)` 在 PostgreSQL repository 里仍然是一个 Python 层顺序尝试器：它按 `QueueEvaluation.executable_ids` 遍历，并逐个调用上述原子 `claim_ready_work_item(...)`。这一步已经把 worker-side selection 收口进 repository，但还没有把“claim next executable”本身写成单个 SQL dequeue primitive。

### Worker 的职责边界

当前 `src/taskplane/worker.py` 的职责边界是：

- 负责 ready 同步、queue evaluation、guardrail materialization
- 负责为 executable candidates 预先生成 workspace metadata
- 负责执行、验证、记录 execution / verification evidence
- 不再负责“最终决定 claim 哪个 task”

这让 worker 更像 orchestration shell，而不是 claim authority。

一个重要细节是：**claim record 先存在，workspace prepare 后发生。**

这意味着如果某个任务已经被 repository claim 成功，那么 `work_claim` 已经是控制面事实，随后才会进入 worktree 创建或确认步骤。

### Workspace 边界

`src/taskplane/workspace.py` 现在只负责工作空间元数据与 worktree 生命周期：

- `build_workspace_spec(...)`：根据 issue number 和 title slug 派生 `branch_name / workspace_path`
- `ensure_workspace(...)`：执行 `git worktree add`
- `WorkspaceManager.prepare(...)`：若 worktree 不存在则创建，然后返回 `workspace_path`
- `WorkspaceManager.release(...)`：删除 `work_claim`，并可选清理 worktree

关键点是：`WorkspaceManager.prepare(...)` **不写 claim**。claim persistence 现在是 repository 的职责，而不是 workspace 的职责。

### 结构化 routing key 与显式验证关联

本轮 schema tightening 还做了两件小但关键的结构调整：

- `work_item.repo` 现在是显式列，不再只存在于 `dod_json->>'repo'`
- `verification_evidence` 现在显式记录 `run_id` 和 `work_id`，不再通过“按 `work_id` 取最新 `execution_run`”来隐式挂接

这两点的意义分别是：

- `repo` 是控制面 routing key，不是 DoD 元数据，应该结构化
- verification evidence 必须绑定到明确的一次 execution run，否则一旦出现重试或并发，很容易挂错父记录

### 路径冲突语义

当前路径冲突仍然是 prefix-style overlap，而不是只看完全相等：

- 相同路径冲突
- 祖先目录与子路径冲突
- 子路径与祖先目录冲突

这套语义用于：

- queue evaluation 阶段的 advisory path-conflict blocking
- repository claim 阶段的 authoritative recheck

也就是说，queue 可以先把任务标成 blocked，但最终是否能 claim，仍由 repository 重新确认。

### 当前已经证明的行为

以下行为已经由测试覆盖并被当前代码证明：

#### 1. claim 是 repository-owned atomic boundary

- `test_in_memory_repository_claim_ready_work_item_records_claim_atomically`
- `test_in_memory_repository_claim_ready_work_item_rejects_overlapping_claimed_paths`

#### 2. repository 会在第一个 executable 候选失败时回退到下一个候选

- `test_in_memory_repository_claim_next_executable_work_item_skips_rejected_first_candidate`
- `test_run_worker_cycle_claims_second_candidate_when_repository_rejects_first`

这说明 claim-next 语义不是“第一个失败就整轮放弃”，而是“第一个失败时，继续尝试后续 executable candidates”。

#### 3. claim 发生在 workspace prepare 之前

- `test_run_worker_cycle_records_claim_before_workspace_prepare`
- `test_workspace_manager_prepare_does_not_write_claim`

这保证了控制面 claim 与文件系统 worktree 创建的职责分离。

#### 4. in-memory repository 已具备最小并发单赢家保证

- `test_in_memory_repository_claim_ready_work_item_allows_only_one_winner_under_competing_threads`
- `test_in_memory_repository_claim_next_executable_work_item_allows_only_one_winner_under_competing_threads`

这些测试通过线程同时发起 claim，并故意放大竞态窗口，验证最终只有一个线程赢得 claim。

#### 5. 过期 claim 不再阻塞调度与 claim

- `test_evaluate_work_queue_ignores_expired_claims_for_path_conflict`
- `test_in_memory_repository_claim_ready_work_item_ignores_expired_conflicting_claims`
- `test_in_memory_repository_lists_only_active_work_claims`
- `test_in_memory_repository_renew_work_claim_updates_expiry_for_matching_token`
- `test_postgres_repository_renew_work_claim_uses_token_match`

这说明 lease 不再只是元数据。过期 claim 会被视为 inactive，不再阻塞 queue path-conflict 或 repository claim，并且当前 owner 可以通过 token-guarded renewal 延长 lease。

#### 6. abandoned `in_progress` work 会在下一次 readiness sync 中恢复

- `test_in_memory_repository_sync_ready_states_recovers_abandoned_in_progress_item_after_expired_lease`
- `test_in_memory_repository_sync_ready_states_keeps_active_in_progress_item_in_progress`
- `test_postgres_repository_sync_ready_states_recovers_abandoned_in_progress_items_in_sql`

这说明系统现在不只会让 expired claim 失效，还会把失去 active claim 的 `in_progress` work 自动降回调度器可重新判断的状态，而不是永久卡死在执行中。

#### 7. workspace prepare 失败会立即回滚 claim，并且长任务支持持续续租

- `test_run_worker_cycle_rolls_back_claim_and_status_when_workspace_prepare_fails`
- `test_run_worker_cycle_renews_claim_after_workspace_prepare`
- `test_run_worker_cycle_renews_claim_multiple_times_during_long_executor`
- `test_shell_executor_calls_heartbeat_while_command_is_running`

这说明恢复链条已经向前推进了一步：如果 claim 成功但 workspace prepare 失败，系统不会留下悬挂 claim 或卡死的 `in_progress` 状态；同时，对于支持 heartbeat 的执行器，lease 也不再只在 prepare 后续租一次，而是可以在长任务运行期间继续保持活跃。

#### 8. 当前 failure policy 已经区分“可重试”与“应阻塞”失败

- `test_run_worker_cycle_requeues_timeout_failure_as_ready`
- `test_run_worker_cycle_requeues_prepare_failure_without_blocking_metadata`
- `test_run_worker_cycle_keeps_verification_failure_blocked`
- `test_run_worker_cycle_marks_needs_decision_metadata_on_blocked_task`
- `test_run_worker_cycle_blocks_when_auto_commit_is_unsafe`

当前最小 failure policy 已经明确：

- `prepare` 失败：立即回滚 claim，状态回到可调度态
- execution `timeout`：记录失败 run，并把任务回到 `pending`，同时持久化 retry/backoff 元数据，待 `next_eligible_at` 到期后才重新进入 `ready`
- `needs_decision`：保持 `blocked`，并显式标记 `decision_required`
- verification failure：保持 `blocked`
- `unsafe_auto_commit_dirty_paths`：视为 non-blocking commit issue，任务仍可判为 `done`

#### 9. retry / backoff 已开始进入控制面持久化字段

- `attempt_count`
- `last_failure_reason`
- `next_eligible_at`
- `test_run_worker_cycle_requeues_timeout_failure_as_ready`
- `test_in_memory_repository_sync_ready_states_respects_future_next_eligible_at`
- `test_in_memory_repository_sync_ready_states_promotes_pending_item_after_retry_window`

这说明 retry policy 已经不再只是 worker 内部瞬时决策。对于可重试失败（当前仅 timeout），系统会把失败原因、尝试次数、以及下次允许进入队列的时间写回 `work_item`，而 repository readiness sync 会据此决定任务是否能重新变成 `ready`。

#### 10. AI 协议归一化与 canonical commit linkage 已经开始收口

- `test_normalize_payload_maps_pause_for_input_to_needs_decision`
- `test_in_memory_repository_records_and_queries_commit_link`
- `test_in_memory_repository_rejects_duplicate_commit_link_for_same_work_item`
- `test_run_worker_cycle_blocks_duplicate_canonical_commit`

当前系统已经开始把 AI 执行稳定性和 git 闭环向控制面收口：

- opencode 返回的 `awaiting_user_input / ask_next_step / paused_for_input` 类 reason code 会被归一化成 `needs_decision`
- canonical commit 不再只是 `execution_run.result_payload_json` 里的临时信息，而是开始进入 `work_commit_link`
- 如果某个 work item 已经存在 canonical commit link，后续自动提交会被阻止，避免“一 issue 多提交”在控制面层面失控

#### 11. task-level GitHub writeback 已进入 DB-first external closure

- `test_sync_issue_status_via_gh_sets_done_label_and_closes_issue`
- `test_sync_issue_status_via_gh_sets_blocked_label_without_closing_issue`
- `test_sync_issue_status_via_gh_sets_decision_required_label`
- `test_run_worker_cycle_syncs_done_status_to_github_after_finalization`
- `test_run_worker_cycle_syncs_blocked_needs_decision_to_github`

当前已经有一个最小但一致的外部闭环：

- DB 先通过 repository-owned `finalize_work_attempt(...)` 落下 task terminal state
- 之后 worker 才调用 GitHub writeback adapter
- task-level writeback 目前只覆盖 `done` / `blocked` / `needs_decision`

这意味着 GitHub 不再只是导入源，task 级别已经开始成为 DB 的下游同步对象。

#### 12. story-level GitHub closure 已接入完成态同步

- `test_run_story_until_settled_syncs_story_done_to_github_when_complete`
- `test_run_story_until_settled_does_not_sync_story_when_incomplete`

当前 story runner 已经具备最小 story-level 外部闭环：

- 先在 DB 语义上确认 `story_complete=True`
- 仅在 story 确实完成时才触发 GitHub writeback
- incomplete / blocked story 不会被提前同步成完成

这使得外部闭环从 task 级进一步扩展到了 story 级，但仍保持 DB-first：GitHub 只是终态同步对象，不参与完成判定。

#### 13. issue / commit / PR runtime linkage 已开始形成闭环

- `test_in_memory_repository_records_and_queries_pull_request_link`
- `test_in_memory_repository_rejects_duplicate_pull_request_link_for_same_work_item`
- `test_run_worker_cycle_records_pull_request_link_when_commit_payload_provides_one`

当前 `pull_request_link` 已经不再只是 schema 预留表。repository 现在支持 runtime 记录和查询 PR linkage，而 worker 会在执行结果已经显式提供 PR 元数据时，把它与 `work_item` 和 canonical commit 一起落到控制面。

这意味着系统已经开始具备 issue / commit / PR 三者的持久化查询闭环，只是还没有进一步扩展到自动创建 PR 或 richer reconciliation。

#### 14. reconciliation 已接入只读 drift 检测层

- `test_build_reconciliation_report_detects_task_done_vs_github_status_drift`
- `test_build_reconciliation_report_detects_story_done_vs_github_status_drift`
- `test_build_reconciliation_report_detects_missing_pr_link_for_done_task`
- `test_build_reconciliation_report_ignores_aligned_rows`

当前已经有一个只读 reconciliation 层，用来比较：

- DB terminal truth
- GitHub normalized issue state / status label
- runtime PR linkage presence

它目前只负责报告 drift，不负责自动修复。这样可以先把 DB/GitHub/PR 的一致性差异显式化，再决定哪些差异适合自动修复，哪些只应该保留为人工审计信号。

#### 15. reconciliation 已接入受限 auto-repair

- `test_repair_reconciliation_drift_repairs_task_status_mismatch_only`
- `test_repair_reconciliation_drift_repairs_story_status_mismatch`

当前 reconciliation 已经从纯只读报告推进到受限自动修复：

- **可自动修复**：task/story 的 GitHub label/state drift
- **仍然只读**：缺失 PR link、PR linkage 冲突、以及更复杂的外部审计问题

这样可以先把最安全、最确定的外部状态漂移收回来，而不在 PR / commit / issue 三方关系仍有歧义时做激进自动修复。

#### 16. 执行成功率硬化已经开始进入运行时链路

- `test_run_worker_cycle_blocks_preflight_when_required_issue_identity_is_missing`
- `test_classify_nonzero_exit_payload_marks_interrupted_retryable`
- `test_classify_nonzero_exit_payload_marks_tooling_error_for_generic_nonzero`
- `test_build_attempt_report_counts_execution_outcomes`

当前系统已经开始把“执行成功率”从经验问题推进成控制面能力：

- worker 在 claim/execution 前有最小 preflight gate，可拦截明显不具备执行条件的 work item
- richer preflight 已开始扩展：file/dir 型任务如果缺少 `planned_paths`，会在 claim/execution 前被直接阻断
- opencode 非零退出不再一律折叠成同一种 blocked，而是开始区分 `interrupted_retryable` 与 `tooling_error`
- worker 侧 failure policy 现在也与该 taxonomy 对齐：`interrupted_retryable` / `timeout` 走 retryable 路径，而 `tooling_error` / `protocol_error` 保持 blocked，不写 retry metadata
- attempt-level report 已经具备更有运营价值的最小聚合能力，可以从 `ExecutionRun` 中统计 done / needs_decision / timeout / protocol_error，以及 invalid payload / non-terminal / interrupted / tooling error 等信号，并给出 first-attempt success、eventual success、average attempts to success 等基础成功率指标
- worker 现在会显式组装 `ExecutionContext` 并传给 executor/verifier，shell adapter 也会将其序列化为 `TASKPLANE_EXECUTION_CONTEXT_JSON`，从而减少执行器在运行时临时重建上下文的隐式耦合
- 最小 session policy 已落地：`timeout` 仍按 fresh-session retry 处理，而 `interrupted_retryable` 会把下一次执行上下文标记成 `resume_candidate`

这还不是完整的 reliability framework，但已经把执行稳定性从“靠日志排查”推进成“运行时链路中显式建模”。

同时，worker 的终态收口已经进一步向 repository 迁移：

- 成功验证后的 `done/blocked` 终态
- `already_satisfied`
- execution failure 的 early-exit（包括 timeout backoff 和 `needs_decision`）
- verification evidence
- canonical commit link

现在都通过 repository 的 `finalize_work_attempt(...)` 统一落库，而不是由 worker 在不同分支里分别拼装。

### 明确不应过度解读的部分

当前实现与测试证明了“repository 边界更安全”，但还不应夸大为完整的分布式锁系统：

- 还没有真实 PostgreSQL integration test 去验证“claim 成功后、workspace prepare 失败”这类后续故障面下的恢复策略
- `claim_next_executable_work_item(...)` 在 PostgreSQL repository 中仍然是 Python 层顺序尝试，而不是单 SQL dequeue primitive
- 目前只有支持 heartbeat 回调的执行器才会在长任务期间持续续租；并非所有执行器都自动具备该能力
- 失败分类虽然已经开始持久化，但仍是 MVP 级策略，尚未引入更细粒度的 per-reason backoff、attempt history、或全局限流控制
- commit linkage 已进入数据库，但 GitHub/PR writeback 仍未成为统一的 repository-owned finalization path
- GitHub / PR writeback 仍未并入统一的 repository-owned finalization 链路
- 当前 auto-repair 只覆盖 task/story 状态漂移；PR linkage drift、自动创建 PR、以及更完整的外部修复链路仍未接上
- 执行成功率硬化目前仍是第一批最小实现，虽然已经有 `attempt_report.py` 与 `attempt_report_cli.py` 作为最小 observability surface，但尚未覆盖更完整的 preflight、更多 executor failure taxonomy、以及 richer dashboard/analytics

### 下一步

当前最直接的下一步是把 recovery hardening 再推进一层，例如：

1. 给更多执行器统一补 heartbeat 能力，而不只依赖支持 callback 的执行路径
2. 将 timeout 之外的可重试失败也纳入持久化 retry/backoff 策略
3. 在已落地的 reliability baseline 之上继续扩展 preflight / executor taxonomy / attempt observability，并继续扩展 PR linkage reconciliation

在此之前，当前文档应该把本轮改造理解为：

**worker 仍负责算候选，repository 已经成为 claim authority，workspace 只负责文件系统工作空间生命周期。**
