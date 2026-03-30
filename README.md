# Stardrifter Orchestration MVP

一个基于 PostgreSQL 的 AI 编排控制面（control plane）实现，当前以 Stardrifter 工作流作为参考适配层。

> 最后更新：2026-03-31（与当前仓库代码结构同步）

## 1. 项目定位

这个仓库同时包含两层能力：

1. 可复用编排底座（substrate core）
2. Stardrifter 场景适配层（GitHub issue 流程、治理层、Story/Task 编排）

适合的使用方式：

- 直接当作单项目/多项目 AI 编排控制面使用
- 作为“通用编排底座 + 场景适配层”的演进起点

## 2. 当前能力（按模块）

### 控制面与状态机

- `sql/control_plane_schema.sql` 定义核心实体：`work_item`、`work_claim`、`execution_run`、`program_epic`、`program_story` 等
- `src/stardrifter_orchestration_mvp/repository/` 提供 PostgreSQL 仓储实现（claim、lease、finalize、状态更新）
- `src/stardrifter_orchestration_mvp/planner.py` / `queue.py` / `guardrails.py` 负责任务可执行性、依赖与安全边界

### GitHub 导入与投影

- `import_cli.py`：GitHub issue 导入到 staging（依赖 `gh` CLI）
- `projection_sync_cli.py`：staging -> `work_item/work_dependency`
- `governance_sync_cli.py`：staging -> `program_epic/program_story`
- `github_writeback.py`：终态回写 GitHub 标签/状态

### 执行链路

- `cli.py`：单次 worker cycle
- `story_runner_cli.py`：按 Story drain 任务
- `supervisor_cli.py`：后台调度循环（分解与执行任务启动）
- `orchestration_loop.py`：story-by-story 循环编排（含 opencode 路径）
- `global_coordinator.py` / `global_coordinator_cli.py`：多 repo 全局资源协调

### 治理与修复

- `governance_state_cli.py`：更新 epic/story execution status
- `governance_report_cli.py` / `governance_priority_cli.py`：治理报表与优先级快照
- `reconciliation_report_cli.py`：DB/GitHub/PR 漂移检查及安全修复

### Web UI 与 API

- `hierarchy_api.py`：FastAPI 服务 + 静态页面托管
- React 控制台静态资源在 `src/stardrifter_orchestration_mvp/static/`
- `frontend/` 为 Vite + React 源码，构建输出直接写入上述 static 目录

## 3. 目录速览

```text
src/stardrifter_orchestration_mvp/
  ├── repository/                  # PostgreSQL 仓储与控制面读写
  ├── console_queries/             # 控制台查询 SQL
  ├── static/                      # Web UI 静态产物（console.bundle.js 等）
  ├── *_cli.py                     # 各类命令行入口
  ├── hierarchy_api.py             # FastAPI API + UI 入口
  └── orchestration/scheduling 相关模块

sql/
  ├── control_plane_schema.sql
  ├── 001_parallel_execution_extensions.sql
  ├── 002_global_coordination.sql
  ├── 003_ui_enhancements.sql
  ├── data_integrity_fixes.sql
  └── data_integrity_triggers.sql

frontend/                          # React + Vite 控制台源码
scripts/                           # 测试与执行脚本
tests/                             # Python/Node/Smoke 测试
docs/                              # 架构与设计文档
```

## 4. 环境要求

- Python `>=3.11`
- PostgreSQL（建议 15/16）
- `gh` CLI（运行 GitHub 导入时需要）
- Node.js（前端开发建议与 CI 一致：22）
- 可选：Docker / Docker Compose（本地 DB 与看板工具）

## 5. 快速开始

### 5.1 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
```

### 5.2 配置数据库连接

```bash
export STARDRIFTER_ORCHESTRATION_DSN='postgresql://stardrifter:stardrifter@localhost:5432/stardrifter_orchestration'
```

### 5.3 初始化数据库 Schema

```bash
psql "$STARDRIFTER_ORCHESTRATION_DSN" -f sql/control_plane_schema.sql
psql "$STARDRIFTER_ORCHESTRATION_DSN" -f sql/001_parallel_execution_extensions.sql
psql "$STARDRIFTER_ORCHESTRATION_DSN" -f sql/002_global_coordination.sql
psql "$STARDRIFTER_ORCHESTRATION_DSN" -f sql/003_ui_enhancements.sql
```

可选（数据完整性修复与触发器）：

```bash
psql "$STARDRIFTER_ORCHESTRATION_DSN" -f sql/data_integrity_fixes.sql
psql "$STARDRIFTER_ORCHESTRATION_DSN" -f sql/data_integrity_triggers.sql
```

### 5.4 GitHub issue -> 控制面

```bash
stardrifter-orchestration-import --repo owner/repo --limit 200
stardrifter-orchestration-project --repo owner/repo
stardrifter-orchestration-governance --repo owner/repo
```

### 5.5 启动执行

单次 worker cycle：

```bash
stardrifter-orchestration-worker --worker-name local-worker
```

按 Story 执行：

```bash
stardrifter-orchestration-story --story-issue-number 123 --worker-name story-runner
```

Supervisor 循环：

```bash
stardrifter-orchestration-supervisor \
  --dsn "$STARDRIFTER_ORCHESTRATION_DSN" \
  --repo owner/repo \
  --project-dir /abs/path/to/project \
  --log-dir /abs/path/to/logs
```

### 5.6 启动 UI

```bash
stardrifter-orchestration-ui --dsn "$STARDRIFTER_ORCHESTRATION_DSN" --host 127.0.0.1 --port 8000
```

打开：

- `http://127.0.0.1:8000/console`
- `http://127.0.0.1:8000/hierarchy`

## 6. 常用 CLI 入口

以下命令定义于 `pyproject.toml -> [project.scripts]`。

| 命令 | 作用 |
| --- | --- |
| `stardrifter-orchestration-worker` | 执行一次 worker cycle |
| `stardrifter-orchestration-story` | 按 story 持续执行直到完成/阻塞 |
| `stardrifter-orchestration-supervisor` | 运行调度循环并启动后台 job |
| `stardrifter-orchestration-loop` | 运行 story-by-story 编排循环 |
| `stardrifter-orchestration-import` | 导入 GitHub issue 到 staging |
| `stardrifter-orchestration-project` | 同步 projection 到 work_item/work_dependency |
| `stardrifter-orchestration-governance` | 同步治理层 epic/story |
| `stardrifter-orchestration-governance-state` | 更新 epic/story execution status |
| `stardrifter-orchestration-governance-report` | 输出治理树与任务关联状态 |
| `stardrifter-orchestration-governance-priority` | 输出执行优先级建议快照 |
| `stardrifter-orchestration-decompose` | 对指定 Story 运行任务分解 |
| `stardrifter-orchestration-triage` | 输出 triage 报告 |
| `stardrifter-orchestration-attempt-report` | 输出执行成功率/重试统计 |
| `stardrifter-orchestration-reconciliation-report` | 检测并可选修复 DB/GitHub 漂移 |
| `stardrifter-orchestration-hierarchy` | 打印 Epic -> Story -> Task 树 |
| `stardrifter-orchestration-ui` | 启动 FastAPI + 控制台 UI |
| `stardrifter-orchestration-operator` | operator request 的统一入口（list/ack/report） |

补充：`global_coordinator_cli.py` 当前主要通过模块方式运行：

```bash
python -m stardrifter_orchestration_mvp.global_coordinator_cli --help
```

## 7. Web API 概览

主要在 `src/stardrifter_orchestration_mvp/hierarchy_api.py`：

- 页面：`/`、`/console`、`/hierarchy`
- Repo 视图：`/api/repos`、`/api/repos/{repo}/summary`、`/api/repos/{repo}/epics`
- 任务与作业：`/api/repos/{repo}/tasks/{work_id}`、`/api/repos/{repo}/jobs`、`/api/repos/{repo}/jobs/{job_id}`
- 动作：`/api/repos/{repo}/epics/{id}/split`、`/stories/{id}/split`、`/tasks/{id}/retry`
- 多项目：`/api/portfolio`、`/api/ai-decisions`、`/api/notifications`、`/api/agents`
- 治理：`/api/repos/{repo}/governance/priority`、`/governance/health`、`/governance/decide`

## 8. 测试

### 全量 Python 测试

```bash
python3 -m pytest -q
```

### 控制台分层测试（推荐）

```bash
scripts/test-console.sh unit

export STARDRIFTER_TEST_POSTGRES_DSN='postgresql://stardrifter:stardrifter@localhost:5432/stardrifter_orchestration'
scripts/test-console.sh integration
scripts/test-console.sh smoke
scripts/test-console.sh all
```

说明：

- `unit` 不依赖 PostgreSQL
- `integration` 和 `smoke` 依赖 `STARDRIFTER_TEST_POSTGRES_DSN`
- CI 工作流 `.github/workflows/console-tests.yml` 默认跑 `unit`

## 9. 前端开发

开发模式：

```bash
cd frontend
npm ci
npm run dev
```

构建产物回写到 Python static 目录：

```bash
cd frontend
npm run build
```

输出目标（由 `frontend/vite.config.ts` 配置）：

- `../src/stardrifter_orchestration_mvp/static/console.bundle.js`
- `../src/stardrifter_orchestration_mvp/static/console.css`

## 10. 本地看板与数据库（可选）

仓库包含 `ops/docker-compose.nocodb.yml`，当前会启动：

- PostgreSQL
- Metabase（非 NocoDB）

```bash
cp .env.nocodb.example .env
docker compose --env-file .env -f ops/docker-compose.nocodb.yml up -d
```

## 11. 关键文档

- `docs/substrate-architecture.md`：底座架构
- `docs/mvp-design.md`：MVP 设计与边界
- `docs/ai-task-testing-strategy.md`：测试策略
- `docs/task-orchestrator-correctness-and-verification-design.md`：正确性与验证设计
- `docs/program-governance-model.md`：治理模型
- `docs/nocodb-integration.md`：看板集成说明（历史命名仍沿用 NocoDB）
- `sql/MIGRATION_GUIDE.md`：SQL 迁移说明

## 12. 当前边界

当前仓库定位是“可运行的编排控制面 MVP + 场景适配层”，仍建议在生产化前补齐：

- 统一迁移工具链（替代手工 `psql`）
- 鉴权与多租户隔离
- 更完整的可观测性（指标、告警、追踪）
- 端到端回归的 CI 服务化环境
