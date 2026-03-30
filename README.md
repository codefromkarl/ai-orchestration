# Stardrifter Orchestration MVP

这是一个 **PostgreSQL-backed AI orchestration control plane** 的参考实现，当前以 Stardrifter 迁移工作流作为首个落地场景。

换句话说，这个仓库现在同时包含两层：

1. **可复用的编排底座（substrate core）**
2. **Stardrifter 专用的 GitHub / governance / story 参考适配层**

如果你只是想把它当成一个项目内编排器来用，直接看当前 README 的运行方式即可。

如果你想评估它如何演化成一个**通用 AI 编排底座**，先看：

- `docs/substrate-architecture.md`
- `docs/mvp-design.md`
- `docs/ai-task-testing-strategy.md`

## 当前包含

- 通用编排底座架构文档：`docs/substrate-architecture.md`
- AI task 开发测试策略：`docs/ai-task-testing-strategy.md`
- 任务编排正确性与验证设计文档：`docs/task-orchestrator-correctness-and-verification-design.md`
- MVP 设计文档：`docs/mvp-design.md`
- Portfolio / Execution 解耦治理文档：`docs/program-governance-model.md`
- NocoDB 集成文档：`docs/nocodb-integration.md`
- PostgreSQL schema：`sql/control_plane_schema.sql`
- NocoDB 只读视图：`sql/nocodb_views.sql`
- Python 任务就绪计算：`src/stardrifter_orchestration_mvp/planner.py`
- Python guardrails 校验：`src/stardrifter_orchestration_mvp/guardrails.py`
- Python 队列评估：`src/stardrifter_orchestration_mvp/queue.py`
- Python 最小 worker：`src/stardrifter_orchestration_mvp/worker.py`
- GitHub task -> work_item 投影器：`src/stardrifter_orchestration_mvp/issue_projection.py`
- Story drain runner：`src/stardrifter_orchestration_mvp/story_runner.py`
- Story runner CLI：`src/stardrifter_orchestration_mvp/story_runner_cli.py`
- projection -> work_item 同步 CLI：`src/stardrifter_orchestration_mvp/projection_sync_cli.py`
- governance 层同步 CLI：`src/stardrifter_orchestration_mvp/governance_sync_cli.py`
- governance 层报表 CLI：`src/stardrifter_orchestration_mvp/governance_report_cli.py`
- triage 报告 CLI：`src/stardrifter_orchestration_mvp/triage_report_cli.py`
- Shell 执行/验证适配器：`src/stardrifter_orchestration_mvp/adapters.py`
- 内存控制面仓库：`src/stardrifter_orchestration_mvp/repository.py`
- PostgreSQL 仓库工厂：`src/stardrifter_orchestration_mvp/factory.py`
- PostgreSQL 环境读取：`src/stardrifter_orchestration_mvp/settings.py`
- 最小测试：`tests/`

当前 worker / claim 边界已经更新为 repository-centric：

- worker 负责 `ready` 同步、queue evaluation、guardrail materialization 与执行/验证
- repository 负责 authoritative claim：
  - `claim_ready_work_item(...)` 是原子 claim primitive
  - `claim_next_executable_work_item(...)` 负责按 executable 顺序尝试 claim
- workspace 只负责 `branch_name / workspace_path / git worktree` 生命周期，不负责写 claim
  - 有 canonical story 的 task 会复用同一个 story 分支 / worktree
  - 无 canonical story 的 task 才退回 task 级 workspace

更完整的设计说明见：`docs/mvp-design.md` 中的 `Repository-centric claim safety` 小节。

## 如何理解“底座”与“适配层”

### 底座（可复用）

这些部分已经接近通用 AI 编排底座：

- `models.py` 中的 work / claim / run / verification 数据模型
- `repository.py` 中的 claim、lease、retry、attempt finalization
- `planner.py` / `queue.py` / `guardrails.py` 中的可执行性与安全性判定
- `worker.py` 中的执行生命周期编排
- `adapters.py` / `workspace.py` 中的执行与工作空间边界
- `sql/control_plane_schema.sql` 中的核心控制面表

### 适配层（当前是 Stardrifter 专用）

这些部分代表了当前仓库的参考落地，而不是底座必须形态：

- GitHub issue intake / normalization / projection
- program epic / story governance 语义
- story decomposition / story runner 流程
- NocoDB 可视化与报表
- GitHub task / story writeback 策略

因此，更准确的理解方式不是“这是一个只能给 Stardrifter 用的编排器”，而是：

> **这是一个已经长出通用控制面内核的编排底座，当前附带了一套 Stardrifter 专用参考适配层。**

## 运行测试

```bash
python3 -m pytest -q
```

## 运行控制台测试工作流

控制台现在有三层测试：

1. **unit** — 前端 helper + action/unit 语义
2. **integration** — PostgreSQL-backed console read model
3. **smoke** — 浏览器级控制台 smoke path

推荐直接使用统一脚本：

```bash
chmod +x scripts/test-console.sh

# 只跑轻量单元/语义测试
scripts/test-console.sh unit

# 跑 unit + DB-backed integration
export STARDRIFTER_TEST_POSTGRES_DSN='postgresql://stardrifter:stardrifter@localhost:5432/stardrifter_orchestration'
scripts/test-console.sh integration

# 只跑 browser smoke
export STARDRIFTER_TEST_POSTGRES_DSN='postgresql://stardrifter:stardrifter@localhost:5432/stardrifter_orchestration'
scripts/test-console.sh smoke

# 全部一起跑
export STARDRIFTER_TEST_POSTGRES_DSN='postgresql://stardrifter:stardrifter@localhost:5432/stardrifter_orchestration'
scripts/test-console.sh all
```

说明：

- `unit` 不依赖 PostgreSQL
- `integration` 和 `smoke` 需要 `STARDRIFTER_TEST_POSTGRES_DSN`
- `smoke` 会临时启动本地控制台并通过 Playwright 走一条最小真实 UI 路径

### Console smoke 当前保护的 UX contract

控制台 smoke 不再只验证“脚本还能继续点下去”，还显式保护两类人类可感知状态：

1. **landing ready**
   - 初始进入 `/console` 时，主输入与加载按钮可见
   - 页面标题已渲染
   - 不存在意外的 blocking modal / stray menu
   - detail drawer 与 workspace panel 处于合理初始状态

2. **post-navigation cleanliness**
   - 切换到 `running_jobs`、`notifications`、`agent_console` 等 workspace 视图后，不应残留意外 overlay 或 stray action menu
   - 打开/关闭 detail 与 confirmation modal 后，页面应返回到可继续工作的状态

这层 smoke 的目标不是做像素级视觉回归，而是保护“人类打开页面后是否会立刻觉得网站处于异常状态”的基本 UX 合同。

## CI-ready 分层建议

当前推荐这样分层：

- **PR / default CI**：只跑 `scripts/test-console.sh unit`
- **数据库可用的开发环境 / 手动验证**：跑 `scripts/test-console.sh integration`
- **完整本地 UI 冒烟**：跑 `scripts/test-console.sh smoke`
- **本地全量验证**：跑 `scripts/test-console.sh all`

仓库已提供一个最小 GitHub Actions workflow：

- `.github/workflows/console-tests.yml`

它默认只执行轻量且稳定的 `unit` 层。

原因：

- `integration` 依赖本地可写 PostgreSQL
- `smoke` 依赖 Playwright 浏览器运行时和可用的数据库种子环境

因此更适合在开发机或后续专门的 self-hosted / service-backed CI 上启用，而不是先把它们硬塞进所有 PR 的默认 pipeline。

如需运行真实 PostgreSQL claim 并发集成测试，可额外设置：

```bash
export STARDRIFTER_TEST_POSTGRES_DSN='postgresql://stardrifter:stardrifter@localhost:5432/stardrifter_orchestration'
python3 -m pytest -q tests/test_repository.py -k "postgres_integration"
```

未设置该环境变量时，相关集成测试会自动跳过。

## 运行 attempt 报表

```bash
stardrifter-orchestration-attempt-report --repo codefromkarl/stardrifter
```

它会输出第一版执行质量摘要，例如：

- total runs
- done runs
- needs decision runs
- timeout runs
- protocol error runs
- invalid payload / non-terminal / interrupted / tooling error runs
- first-attempt success runs
- eventual success runs
- average attempts to success

## 启动 NocoDB 看板

```bash
cp .env.nocodb.example .env
docker compose --env-file .env -f ops/docker-compose.nocodb.yml up -d
```

## 构造 PostgreSQL Repository

```python
from stardrifter_orchestration_mvp.factory import build_postgres_repository
from stardrifter_orchestration_mvp.settings import load_postgres_settings_from_env

settings = load_postgres_settings_from_env()
repository = build_postgres_repository(dsn=settings.dsn)
```

## 运行单次 Worker Cycle

```bash
export STARDRIFTER_ORCHESTRATION_DSN='postgresql://user:pass@localhost:5432/stardrifter_orchestration'
python3 -m stardrifter_orchestration_mvp.cli --worker-name worker-a --allowed-wave wave-5
```

## 从 GitHub issue 同步到 work_item

```bash
export STARDRIFTER_ORCHESTRATION_DSN='postgresql://stardrifter:stardrifter@localhost:5432/stardrifter_orchestration'

python3 -m stardrifter_orchestration_mvp.import_cli \
  --repo codefromkarl/stardrifter \
  --limit 200

python3 -m stardrifter_orchestration_mvp.projection_sync_cli \
  --repo codefromkarl/stardrifter

python3 -m stardrifter_orchestration_mvp.governance_sync_cli \
  --repo codefromkarl/stardrifter

python3 -m stardrifter_orchestration_mvp.governance_report_cli \
  --repo codefromkarl/stardrifter
```

当前两段职责分离：

- `import_cli` 负责 GitHub -> staging
- `projection_sync_cli` 负责 staging -> `work_item/work_dependency`
- `governance_sync_cli` 负责 staging -> `program_epic/program_story`
- `governance_report_cli` 负责从 PostgreSQL 输出治理总树与当前 execution 面

## 当前 claim safety 状态

当前已经具备三层能力：

- PostgreSQL claim path 使用 `FOR UPDATE SKIP LOCKED` + `work_claim` 路径冲突复检
- worker 不再自己决定最终 claim 哪个 executable task，而是交给 repository 的 `claim_next_executable_work_item(...)`
- in-memory repository 已有多线程竞争测试，验证 direct claim 和 claim-next 都只有单赢家
- `work_claim` 现在不仅带 lease metadata，而且未过期 claim 才会被视为 active；worker 在 prepare 后会续租一次，支持 heartbeat 的执行器在长任务期间也会继续续租，expired claim 不再持续阻塞 queue / claim
- 失去 active claim 的 abandoned `in_progress` work 会在下一次 readiness sync 时自动恢复，不再永久卡死
- 如果 workspace prepare 失败，worker 会立即删除 claim 并回退状态，不留下悬挂 claim
- 当前最小 failure policy 已落地：prepare failure 与 execution timeout 会回到可调度态；verification failure / needs decision 仍保持 blocked
- timeout 不再立即回到 `ready`，而是会持久化 `attempt_count / last_failure_reason / next_eligible_at`，等 backoff 窗口过去后再重新进入队列
- opencode 的 paused / ask-next-step 类 reason code 已归一化为 `needs_decision`，canonical commit 也开始持久化到数据库并阻止重复自动提交
- success-path 与 execution-failure early-exit 都已经进入 repository-owned `finalize_work_attempt(...)`，worker 不再手工拼接 run / verification / commit / retry 状态落库
- 现在已有第一版 operator-facing success-rate 报表：`stardrifter-orchestration-attempt-report`
- task-level GitHub writeback 已落地：在 DB terminalization 成功之后，同步 `done / blocked / needs_decision` 到 GitHub issue 标签与 open/closed 状态
- story-level GitHub closure 也已落地：只有当 story 在 DB 语义上真正 complete 时，才同步 GitHub story issue 为完成
- `pull_request_link` 已接入 runtime：如果执行结果显式给出 PR 元数据，repository 会将 issue / commit / PR linkage 一起持久化
- 现在已有 reconciliation 层：既能只读检测 DB / GitHub / PR drift，也能在受限模式下自动修复 task/story 的安全 label/state drift
- 执行链路已开始做成功率硬化：worker 有最小 preflight 拦截，opencode 非零退出会区分 interrupted/tooling_error，且已有 attempt-level report 基础能力
- worker 现在会显式组装 `ExecutionContext`，再传给 executor/verifier；shell adapter 也会导出 `STARDRIFTER_EXECUTION_CONTEXT_JSON`，这是借鉴 gsd-2 的 context packaging 思路后在 DB-first 架构中的最小落地
- 现在已有最小 session policy：timeout 重试仍是 `fresh_session`，`interrupted_retryable` 会被标记为 `resume_candidate`，并体现在 `ExecutionContext` 中
- richer preflight 也已开始落地：除了缺失 issue identity 之外，系统还会在 CLI 启动前拦截明显不可执行的环境/命令问题
- CLI 侧也已有保守 preflight：不存在的 `workdir`、缺失的 executor binary、缺失的 verifier binary 都会在 worker 启动前被直接拒绝
- CLI 侧还会拒绝明显非法的 `worktree-root` 目录树（例如父路径是文件而非目录）
- `work_item.repo` 已结构化为列，`verification_evidence` 也改为显式关联 execution run

当前仍未补足的部分：

- 不是所有执行器都已经支持长任务 heartbeat / 多次续租
- retry/backoff 仍是 MVP 级别，目前只覆盖 timeout，尚未形成更细粒度的 per-reason 策略
- GitHub / PR 写回还没有进入统一的 repository-owned finalization 闭环
- 当前 auto-repair 只覆盖 task/story 状态漂移；PR linkage drift 仍保持只读审计，自动 PR 创建也仍未接入 runtime
- preflight、executor taxonomy、attempt metrics 目前还是第一批最小实现，尚未扩展到更完整的中断恢复与 success-rate dashboard

## 按 Story 连续执行

```bash
export STARDRIFTER_ORCHESTRATION_DSN='postgresql://stardrifter:stardrifter@localhost:5432/stardrifter_orchestration'
python3 -m stardrifter_orchestration_mvp.story_runner_cli \
  --story-issue-number 29 \
  --worker-name story-runner \
  --allowed-wave wave-2
```

当前 `story_runner_cli` 会：

- 从 `work_item` 中加载属于该 Story 的 task
- 在同一个 story worktree / branch 中连续调用 worker，直到全部完成或出现阻塞
- 当 Story 下所有 task 完成时，自动将 story 分支合并回基线分支
- 合并成功后才将 Story 视为完成
- 输出 `complete` 或 `incomplete`

运行约束：

- `--workdir` / `--project-dir` 不应直接指向人类开发者正在修改的脏工作树
- 推荐为 orchestrator 准备单独的 clean clone，再在其下创建 `.orchestration-worktrees/`
- 否则 story 完成后的 merge 会被本地未提交改动阻塞，控制面会出现“task done 但 story 无法收口”的假完成

## 按 Story 先做 Task Decomposition

```bash
export STARDRIFTER_ORCHESTRATION_DSN='postgresql://stardrifter:stardrifter@localhost:5432/stardrifter_orchestration'
python3 -m stardrifter_orchestration_mvp.story_decomposition_cli \
  --repo codefromkarl/stardrifter \
  --story-issue-number 42 \
  --workdir /home/yuanzhi/Develop/playground/gametest \
  --decomposer-command "python3 -m stardrifter_orchestration_mvp.opencode_story_decomposer"
```

当前 `story_decomposition_cli` 会：

- 只处理 `execution_status=decomposing` 的 Story
- 调用 AI / shell decomposer 为该 Story 生成 Task
- 自动执行 GitHub -> PG refresh
- 若出现可投影 task，则把 Story 推进到 `active`
- 若 AI 判断 Story 边界失真，则落到 `needs_story_refinement`

## 运行常驻 Supervisor

```bash
export STARDRIFTER_ORCHESTRATION_DSN='postgresql://stardrifter:stardrifter@localhost:5432/stardrifter_orchestration'
python3 -m stardrifter_orchestration_mvp.supervisor_loop \
  --dsn "$STARDRIFTER_ORCHESTRATION_DSN" \
  --repo codefromkarl/stardrifter \
  --project-dir /home/yuanzhi/Develop/playground/gametest \
  --worktree-root /home/yuanzhi/Develop/playground/gametest/.orchestration-worktrees \
  --log-dir /home/yuanzhi/Develop/tools/stardrifter-orchestration-mvp/.run-logs \
  --max-parallel-jobs 2
```

当前 `supervisor_loop` 会：

- 在控制面内部轮询 `v_story_decomposition_queue` 与 `v_active_task_queue`
- 通过 `execution_job` 持久化后台 job 的 pid / command / log / terminal status
- 自动启动 decomposition job 和 story worker job
- 以 Story 为并行批次；同一 Story 内的 task 不再由 supervisor 并发拆成多个 worker
- 自动回收已结束子进程，并继续派发下一批

推荐运行方式：

- `--project-dir` 指向 orchestration 专用 clean clone
- `--worktree-root` 指向该 clean clone 下的独立目录，例如 `<clean-clone>/.orchestration-worktrees`
- 不要把 supervisor 直接挂在人工开发中的 `main` 工作树上

## Operator / governance workflow

这一组命令适合放在 supervisor 与治理报表之间使用：先看总览，再处理 open operator requests，必要时刷新某个 Epic 的 runtime state。它们只读取或更新治理状态，不会启动 worker。

### Dashboard overview

```bash
export STARDRIFTER_ORCHESTRATION_DSN='postgresql://stardrifter:stardrifter@localhost:5432/stardrifter_orchestration'
python3 -m stardrifter_orchestration_mvp.dashboard_cli \
  --repo codefromkarl/stardrifter
```

该命令会先输出仓库级摘要，例如 `active_epics`、`rows`、`open_operator_requests`，然后按 `operator_reason` 和 `epic` 输出当前需要人工关注的聚合视图。

### Unified operator CLI

```bash
export STARDRIFTER_ORCHESTRATION_DSN='postgresql://stardrifter:stardrifter@localhost:5432/stardrifter_orchestration'

stardrifter-orchestration-operator list \
  --repo codefromkarl/stardrifter

stardrifter-orchestration-operator ack \
  --repo codefromkarl/stardrifter \
  --epic-issue-number 42 \
  --reason-code operator_decision_needed \
  --closed-reason resolved_in_governance

stardrifter-orchestration-operator report \
  --repo codefromkarl/stardrifter
```

`list` 会逐条输出 open request，包含 `epic`、`reason`、`remaining`、`blocked`、`status` 和 `summary`；如果没有 open request，会打印 `no open operator requests`。`ack` 会关闭指定 request，并输出关闭结果；如果找不到匹配项，会返回非零退出码。`report` 会按 `reason` 分组汇总 open requests，并给出 `requests`、`epics`、`oldest_epic` 与 `oldest_opened_at`。

### Epic resume, preview first, then apply

```bash
export STARDRIFTER_ORCHESTRATION_DSN='postgresql://stardrifter:stardrifter@localhost:5432/stardrifter_orchestration'

python3 -m stardrifter_orchestration_mvp.epic_resume_cli \
  --repo codefromkarl/stardrifter \
  --epic-issue-number 42 \
  --dry-run

python3 -m stardrifter_orchestration_mvp.epic_resume_cli \
  --repo codefromkarl/stardrifter \
  --epic-issue-number 42
```

这个 refresh/resume CLI 会根据当前 story execution 状态和 open operator requests 重新计算该 Epic 的 runtime state，输出 `mode`、`status`、`operator_attention` 和 `open_requests`。它不会启动 worker；`--dry-run` 只预览刷新后的 runtime state，不会持久化，去掉 `--dry-run` 才会把刷新结果写回数据库。

## 查看为什么 issue 没进执行表

```bash
export STARDRIFTER_ORCHESTRATION_DSN='postgresql://stardrifter:stardrifter@localhost:5432/stardrifter_orchestration'
python3 -m stardrifter_orchestration_mvp.triage_report_cli \
  --repo codefromkarl/stardrifter
```

## 查看治理优先级建议

```bash
export STARDRIFTER_ORCHESTRATION_DSN='postgresql://stardrifter:stardrifter@localhost:5432/stardrifter_orchestration'
python3 -m stardrifter_orchestration_mvp.governance_priority_cli \
  --repo codefromkarl/stardrifter
```

该报告刻意区分三件事：

- 当前必须先做的 active task / governance task
- 已进入 `decomposing`、等待 AI 拆 task 的 Story
- 已入总树但仍属于下一波次的 gated / planned Epic

当前 Story 状态语义已经收敛为：

- `decomposing`: Story 已经进入当前波次，但还没有形成可执行 task 容器；应先由 AI 做 task decomposition
- `active`: Story 已经有可执行 task，允许进入 `v_active_task_queue`
- `needs_story_refinement`: AI 判断 Story 边界本身失真，不能继续只靠拆 task 解决，需回到治理层重构 Story

当前 triage 报告会先给总数：

- `unprojected_tasks`
- `stories_without_projected_tasks`

当前 CLI 仍是 MVP 入口：

- 不传命令时，默认 executor/verifier 仍是 `noop`
- 传入命令后，会通过 `subprocess` 在指定 `workdir` 执行
- 执行时会注入环境变量：`STARDRIFTER_WORK_ID`、`STARDRIFTER_WORK_TITLE`、`STARDRIFTER_WORK_LANE`、`STARDRIFTER_WORK_WAVE`
- `execution_run` 与 `verification_evidence` 会记录 `exit_code`、`elapsed_ms`、`stdout_digest`、`stderr_digest`
- `opencode_task_executor` 现在要求 `opencode` 以结构化 JSON 输出最终结果：
  - `outcome=done`
  - `outcome=already_satisfied`
  - `outcome=blocked`
  - `outcome=needs_decision`
- 如果 issue 的 DoD 在当前仓库状态中已经满足，执行器要求返回 `already_satisfied`，而不是 `blocked/no-repo-change`
- 执行器会拒绝“还在研究 / 等上下文 / 背景任务进行中”这类非终态结果，并将其视为协议错误
- `opencode_task_executor` 现在带任务级 timeout watchdog：
  - 默认 `1200` 秒
  - 可通过 `STARDRIFTER_OPENCODE_TIMEOUT_SECONDS` 或 loop 参数 `--opencode-timeout-seconds` 覆盖
  - 超时会直接落成 `blocked`
  - `blocked_reason=timeout`
- `work_item` 现在会持久化：
  - `blocked_reason`
  - `decision_required`
- `execution_run` 现在会持久化：
  - `result_payload_json`
- task 验证通过且存在安全可提交的 `changed_paths` 时，会自动创建 git commit
  - commit message 规则：`chore(task-<issue-number>): complete task #<issue-number>`
  - commit body：`refs #<issue-number>`
  - 如果任务触达的文件在执行前已是脏文件，自动提交会被拒绝，task 会转为 `blocked`

## 当前 Story 执行能力

现在已经具备两层能力：

- `github_issue_normalized + github_issue_relation` 可投影出 task 级 `work_item`
- `story_runner` 可按某个 Story 的 task 集合在共享 story worktree 中持续调度，直到全部完成或出现阻塞
- Story 完成后会自动尝试将 story 分支合并回基线分支，再回写 GitHub story 完成态

当前仍未落地的部分：

- 自动 PR 创建与 PR 链路统一收口

## 运行真实命令

```bash
export STARDRIFTER_ORCHESTRATION_DSN='postgresql://user:pass@localhost:5432/stardrifter_orchestration'
python3 -m stardrifter_orchestration_mvp.cli \
  --worker-name worker-a \
  --allowed-wave wave-5 \
  --workdir /home/yuanzhi/Develop/playground/gametest \
  --executor-command 'python3 -m pytest -q tests/test_worker.py' \
  --verifier-command 'python3 -m pytest -q'
```

## 下一步

- 增加 GitHub PR link 自动回写
- 增加真实 PostgreSQL 多 worker 并发集成测试
- 增加真实命令白名单/沙箱策略
