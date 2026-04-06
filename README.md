# Taskplane

Taskplane 是一个以 PostgreSQL 为控制面事实源的 AI 编排系统，用来接收任务、计算可执行工作、调度执行器、沉淀验证证据，并通过 API / 控制台暴露运行态与治理态。

> 最后更新：2026-04-06

## 项目定位

Taskplane 的核心目标是：

- 以 PostgreSQL 作为编排真相源
- 将需求入口、治理层、执行层和验证证据连接成闭环
- 让 operator 能看见、干预、恢复、推进 AI 执行链路

更完整的架构与边界说明见：

- `docs/architecture-overview.md`
- `docs/substrate-architecture.md`
- `docs/adr/0001-engineering-boundaries.md`

## 当前能力概览

当前仓库已覆盖以下核心能力：

- 任务接入与投影
  - GitHub issue 导入、projection、governance sync
- 自然语言需求入口
  - submit / answer / approve
  - console / API 支持 reject / revise
- 控制面与调度
  - planner / queue / guardrails / supervisor / story_runner / worker
- 多轮会话运行时
  - execution session / checkpoint / wakeup / policy resolution
- 执行与验证
  - executor / verifier / workspace / writeback 适配边界
- 可观测性与操作台
  - FastAPI + React 控制台
  - notification / event log / DLQ / operator request ack

## 快速开始

### 1. 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
```

### 2. 准备配置

```bash
cp taskplane.toml.example taskplane.toml
```

最小配置示例：

```toml
[postgres]
dsn = "postgresql://stardrifter:stardrifter@localhost:5432/taskplane"

[console.repo_workdirs]
"owner/repo" = "/abs/path/to/project"

[console.repo_log_dirs]
"owner/repo" = "/abs/path/to/logs"
```

### 3. 启动本地依赖并应用 migration

```bash
taskplane-dev up
```

### 4. 检查环境

```bash
taskplane-doctor --repo owner/repo
```

数据库迁移细节见：

- `sql/MIGRATION_GUIDE.md`

## 推荐日常工作流

如果你只想保留最少的用户入口，推荐统一走三命令工作流：

```bash
taskplane-workflow link
taskplane-workflow intake "实现认证系统，包含 JWT 登录、刷新 token、前端登录页和权限守卫"
taskplane-workflow status
```

完整使用说明见：

- `docs/workflows/three-command-workflow.md`
- `docs/README.md`

## 常用命令

| 命令 | 作用 |
| --- | --- |
| `taskplane-dev up` | 启动本地依赖并应用核心 migration |
| `taskplane-doctor` | 检查本地配置、依赖和 DB 连通性 |
| `taskplane-workflow` | 高层三命令入口：link / intake / status |
| `taskplane-demo seed` | 注入 demo 数据 |
| `taskplane-import` | 导入 GitHub issue 到 staging |
| `taskplane-project` | 同步 projection 到执行视图 |
| `taskplane-governance` | 同步治理视图 |
| `taskplane-worker` | 执行一次 worker cycle |
| `taskplane-story` | 按 story 执行直到完成/阻塞 |
| `taskplane-supervisor` | 运行调度循环并启动后台 job |
| `taskplane-ui` | 启动 FastAPI + 控制台 UI |

更完整的入口说明与操作手册，请看：

- `docs/README.md`
- `docs/workflows/three-command-workflow.md`

## 控制台与 API

页面入口：

- `/`
- `/console`
- `/hierarchy`

关键 API：

- 系统状态：`/api/system/status`
- 自然语言 intake：
  - `GET /api/repos/{repo}/intents`
  - `POST /api/repos/{repo}/intents`
  - `POST /api/intents/{intent_id}/answer`
  - `POST /api/intents/{intent_id}/approve`
  - `POST /api/intents/{intent_id}/reject`
  - `POST /api/intents/{intent_id}/revise`
- Repo 视图：`/api/repos`、`/api/repos/{repo}/summary`
- 任务与作业：`/api/repos/{repo}/tasks/{work_id}`、`/api/repos/{repo}/jobs`

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

## 文档导航

优先阅读顺序：

1. `README.md`
2. `docs/README.md`
3. 按主题进入具体文档

关键文档：

- `docs/README.md`
- `docs/workflows/three-command-workflow.md`
- `docs/architecture-overview.md`
- `docs/substrate-architecture.md`
- `docs/program-governance-model.md`
- `docs/product-roadmap.md`
- `docs/natural-language-intake-followup-plan.md`
- `sql/MIGRATION_GUIDE.md`
