# Taskplane

Taskplane 是一个以 PostgreSQL 为控制面事实源的 AI 编排系统，用来接收任务、计算可执行工作、调度执行器、沉淀验证证据，并通过 API / 控制台暴露运行态与治理态。

> 最后更新：2026-04-02

## 项目功能

当前项目已经覆盖一条完整的编排闭环：

- 任务接入与投影
  - 从 GitHub issue 导入 staging 数据
  - 投影到 `work_item / work_dependency / work_target`
  - 同步治理层 `program_epic / program_story`
- 控制面与调度
  - 基于 PostgreSQL 的 claim、lease、retry、finalize
  - `planner / queue / guardrails` 计算可执行任务并应用执行前约束
  - `supervisor / story_runner / worker` 组成分层执行链路
- 多轮会话运行时
  - `execution_session / execution_checkpoint / execution_wakeup / policy_resolution`
  - 支持 checkpoint、wait、resume、policy resolution 和会话恢复
- 执行与验证
  - shell、opencode、codex、browser 等执行器接入
  - verifier、workspace、git commit、writeback 通过 adapter 边界接入
- 可观测性与操作台
  - artifact、event log、notification、agent pool、DLQ
  - FastAPI + React 控制台展示任务、会话、作业、通知和治理信息

## 架构设计

### 分层

```text
外部系统
  ├─ GitHub
  ├─ Operator / CLI
  ├─ Browser UI
  └─ 目标代码仓库 / worktree

控制面
  ├─ work_item / work_dependency / work_target / work_claim
  ├─ execution_run / verification_evidence / execution_job
  ├─ execution_session / execution_checkpoint / execution_wakeup / policy_resolution
  └─ artifact / event_log / dead_letter_queue / notification_queue

编排核心
  ├─ repository
  ├─ planner / queue / guardrails
  ├─ supervisor / scheduling_loop
  ├─ story_runner
  ├─ worker
  └─ session_runtime_loop

适配层
  ├─ intake / projection / governance sync
  ├─ executor / verifier
  ├─ workspace / git / writeback
  └─ API / frontend
```

### 关键边界

- PostgreSQL 是编排真相源
  - GitHub 是输入源和回写目标，不是状态机真相
- Repository 是权威执行边界
  - worker 负责计算候选
  - repository 负责原子 claim、lease、finalize
- Worker 是 orchestration shell
  - queue evaluation 在 worker
  - authoritative claim / terminalization 在 repository
  - 外部 writeback 发生在 DB 终态之后
- Session runtime 是显式循环
  - `session_runtime_loop` 通过 checkpoint / wakeup / policy resolution 驱动可恢复会话
- Adapter 是可插拔执行边界
  - executor、verifier、workspace、writeback、intake 都通过协议层接入

### 主执行链路

```text
GitHub issue
  -> import / sync
  -> staging tables
  -> projection / governance sync
  -> work graph + governance tables
  -> supervisor
  -> story_runner
  -> worker
  -> repository claim
  -> workspace prepare
  -> executor / verifier
  -> repository finalize
  -> 可选 writeback
```

### 关键模块

- 控制面内核
  - `src/taskplane/repository/`
  - `src/taskplane/planner.py`
  - `src/taskplane/queue.py`
  - `src/taskplane/guardrails.py`
- 编排运行时
  - `src/taskplane/worker.py`
  - `src/taskplane/story_runner.py`
  - `src/taskplane/scheduling_loop.py`
  - `src/taskplane/session_runtime_loop.py`
- 适配层
  - `src/taskplane/adapters.py`
  - `src/taskplane/task_verifier.py`
  - `src/taskplane/workspace.py`
  - `src/taskplane/github_writeback.py`
  - `src/taskplane/protocols.py`
- 操作台
  - `src/taskplane/hierarchy_api.py`
  - `src/taskplane/console_queries/`
  - `frontend/`

## 目录速览

```text
src/taskplane/
  ├── repository/                  # PostgreSQL 控制面实现
  ├── console_queries/             # 控制台查询模型
  ├── static/                      # 前端构建产物
  ├── *_cli.py                     # CLI 入口
  ├── hierarchy_api.py             # FastAPI 服务入口
  ├── worker.py                    # task 级执行壳层
  ├── story_runner.py              # story 粒度 drain 执行
  ├── scheduling_loop.py           # supervisor 调度循环
  └── session_runtime_loop.py      # 多轮会话运行时

sql/
  ├── control_plane_schema.sql
  ├── 001_parallel_execution_extensions.sql
  ├── 002_global_coordination.sql
  ├── 003_ui_enhancements.sql
  ├── 004_artifact_store.sql
  ├── 005_dlq_and_observability.sql
  ├── 006_executor_routing_profiles.sql
  ├── data_integrity_fixes.sql
  └── data_integrity_triggers.sql

frontend/                          # React + Vite 控制台源码
tests/                             # Python / Node / smoke 测试
docs/                              # 架构与设计文档
```

## 环境要求

- Python `>=3.11`
- PostgreSQL `15+`
- Node.js `22` 左右
- `gh` CLI
  - 需要运行 GitHub 导入 / 回写时使用
- 可选：Docker / Docker Compose

## 快速开始

### 1. 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
```

### 2. 配置数据库连接

```bash
export TASKPLANE_DSN='postgresql://stardrifter:stardrifter@localhost:5432/taskplane'
```

### 3. 初始化 Schema

```bash
psql "$TASKPLANE_DSN" -f sql/control_plane_schema.sql
psql "$TASKPLANE_DSN" -f sql/001_parallel_execution_extensions.sql
psql "$TASKPLANE_DSN" -f sql/002_global_coordination.sql
psql "$TASKPLANE_DSN" -f sql/003_ui_enhancements.sql
psql "$TASKPLANE_DSN" -f sql/004_artifact_store.sql
psql "$TASKPLANE_DSN" -f sql/005_dlq_and_observability.sql
psql "$TASKPLANE_DSN" -f sql/006_executor_routing_profiles.sql
```

可选：

```bash
psql "$TASKPLANE_DSN" -f sql/data_integrity_fixes.sql
psql "$TASKPLANE_DSN" -f sql/data_integrity_triggers.sql
```

### 4. 导入与投影

```bash
taskplane-import --repo owner/repo --limit 200
taskplane-project --repo owner/repo
taskplane-governance --repo owner/repo
```

### 5. 运行执行链路

单次 worker：

```bash
taskplane-worker --worker-name local-worker
```

按 Story drain：

```bash
taskplane-story --story-issue-number 123 --worker-name story-runner
```

Supervisor 循环：

```bash
taskplane-supervisor \
  --dsn "$TASKPLANE_DSN" \
  --repo owner/repo \
  --project-dir /abs/path/to/project \
  --log-dir /abs/path/to/logs
```

### 6. 启动控制台

```bash
taskplane-ui --dsn "$TASKPLANE_DSN" --host 127.0.0.1 --port 8000
```

打开：

- `http://127.0.0.1:8000/console`
- `http://127.0.0.1:8000/hierarchy`

## 常用命令

| 命令 | 作用 |
| --- | --- |
| `taskplane-worker` | 执行一次 worker cycle |
| `taskplane-story` | 按 story 执行直到完成/阻塞 |
| `taskplane-supervisor` | 运行调度循环并启动后台 job |
| `taskplane-loop` | 运行 story-by-story 编排循环 |
| `taskplane-import` | 导入 GitHub issue 到 staging |
| `taskplane-project` | 同步 projection 到执行视图 |
| `taskplane-governance` | 同步治理视图 |
| `taskplane-governance-state` | 更新 epic/story execution status |
| `taskplane-governance-report` | 输出治理树与任务关联状态 |
| `taskplane-governance-priority` | 输出优先级建议快照 |
| `taskplane-decompose` | 对指定 Story 运行任务分解 |
| `taskplane-reconciliation-report` | 检测并可选修复 DB / GitHub 漂移 |
| `taskplane-ui` | 启动 FastAPI + 控制台 UI |

补充：

```bash
python -m taskplane.global_coordinator_cli --help
```

## 测试

全量 Python 测试：

```bash
python -m pytest -q
```

控制台分层测试：

```bash
scripts/test-console.sh unit

export TASKPLANE_TEST_POSTGRES_DSN='postgresql://stardrifter:stardrifter@localhost:5432/taskplane'
scripts/test-console.sh integration
scripts/test-console.sh smoke
scripts/test-console.sh all
```

## 前端开发

开发：

```bash
cd frontend
npm ci
npm run dev
```

构建：

```bash
cd frontend
npm run build
```

构建产物输出到：

- `src/taskplane/static/console.bundle.js`
- `src/taskplane/static/console.css`

## 本地数据库与看板

```bash
cp .env.nocodb.example .env
docker compose --env-file .env -f ops/docker-compose.nocodb.yml up -d
```

当前 compose 文件会启动：

- PostgreSQL
- Metabase

## 关键文档

- `docs/architecture-overview.md`
- `docs/substrate-architecture.md`
- `docs/mvp-design.md`
- `docs/ai-task-testing-strategy.md`
- `docs/program-governance-model.md`
- `sql/MIGRATION_GUIDE.md`
