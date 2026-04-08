<div align="center">
  <h1>Taskplane</h1>
  <p><strong>以 PostgreSQL 为真相源的 AI 执行控制面</strong></p>
  <p><em>AI Orchestration · Control Plane · Operator Console · Durable Sessions</em></p>
  <p>
    <img src="https://img.shields.io/badge/Python-%3E%3D3.11-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python >=3.11" />
    <img src="https://img.shields.io/badge/PostgreSQL-Control%20Plane-336791?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL control plane" />
    <img src="https://img.shields.io/badge/FastAPI-API-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
    <img src="https://img.shields.io/badge/React%20%2B%20Zustand-Console-61DAFB?style=flat-square&logo=react&logoColor=black" alt="React and Zustand console" />
  </p>
  <p>
    <a href="./docs/workflows/three-command-workflow.md">Quick Start</a> ·
    <a href="./docs/README.md">Docs</a> ·
    <a href="./docs/architecture-overview.md">Architecture</a> ·
    <a href="./sql/MIGRATION_GUIDE.md">Migrations</a>
  </p>
</div>

> 最后更新：2026-04-08

## 项目简介

Taskplane 不是“再包一层 AI CLI”的薄封装，也不是通用项目管理 SaaS。它解决的是另一类问题：当一个需求要经过 intake、review、分解、执行、验证、回写和人工介入时，如何让整条链路有统一真相源、可审计证据和可恢复运行态。

这个仓库当前提供的就是这层控制面能力：以 PostgreSQL 持久化工作图、执行记录、验证证据、session 和记忆化运行状态，由 Python 编排核心驱动执行，由 FastAPI + React 控制台暴露 operator 观察和干预入口。

## 为什么需要 Taskplane

在真实的 AI 执行链路里，失败通常不是因为“模型不够聪明”，而是因为运行真相分散在多个地方：

- 需求在聊天、issue、前端状态和脚本之间来回漂移
- 任务是否可执行、谁在执行、执行到哪一步缺少统一事实源
- 执行结果、验证证据和人工决策没有稳定落点
- 任务阻塞、澄清、审批、恢复和重试只能靠人肉追踪

Taskplane 的目标就是把这些运行态收口到一个可治理的控制面里。

## 适用场景

- 需要把 GitHub issue、自然语言需求和执行任务统一到同一条编排链路
- 需要 operator 能看到 blocked、review、approval、running jobs 和恢复路径
- 需要按 story / task 组织执行，并沉淀验证证据、checkpoint、session 状态
- 需要在同一个仓库里切换不同执行器，例如 `opencode`、`codex`、`claude-code`
- 需要先在本地创建任务并推进，再决定是否回写到 GitHub 治理面

## 不适合什么

Taskplane 当前不定位为：

- 通用协同办公平台
- 团队聊天工具
- 任意内容创作系统
- “输入一句话自动完成整个项目”的全自治代理
- 用来替代所有底层 CLI 的单一超入口

## 核心能力

- **统一控制面**：将 `work_item`、依赖、claim、execution run、verification evidence、session 等运行事实收口到 PostgreSQL。
- **双入口接入**：同时支持 GitHub issue 导入链路和自然语言 intake / review / promotion 链路。
- **Story / Task 编排**：通过 `supervisor`、`story_runner`、`worker` 组织分解、调度、执行、验证与回写。
- **多执行器路由**：工作流级执行器支持 `opencode`、`codex`、`claude-code`，并允许默认、fallback、planning 分仓库配置。
- **Local-first 模式**：可直接从本地自然语言需求提升出 work item，不强依赖 GitHub issue 编号。
- **Operator Console**：提供 FastAPI + React + Zustand 控制台，暴露运行态、阻塞项、待决策项和系统诊断。

## 架构概览

```mermaid
flowchart LR
  U["Operator / CLI / Console"] --> I["Intake / Review / Promotion"]
  GH["GitHub Issues"] --> I
  I --> DB["PostgreSQL Truth Substrate"]
  DB --> O["Supervisor / Story Runner / Worker"]
  O --> E["Executors: OpenCode / Codex / Claude Code"]
  O --> V["Verifier / Workspace / Writeback"]
  E --> R["Target Repository / Worktree"]
  V --> R
  UI["FastAPI + React Console"] --> DB
```

如果你想看表职责、模块边界和完整主链路，请直接读 `docs/architecture-overview.md` 与 `docs/substrate-architecture.md`。

## 技术栈

- Python 3.11+
- PostgreSQL
- FastAPI + Uvicorn
- React 18 + Zustand + Vite
- Git worktree / shell executor adapters

## 快速开始

### 环境要求

- Python 3.11+
- PostgreSQL
- 本地可写工作目录

### 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
```

### 配置

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

[workflow.repo_default_executor]
"owner/repo" = "opencode"

[workflow.repo_fallback_executor]
"owner/repo" = "codex"

[workflow.repo_planning_executor]
"owner/repo" = "claude-code"
```

如果你要让 `supervisor` 直接驱动 story 级执行器，可继续配置：

```toml
[supervisor.repo_story_executor_commands]
"owner/repo" = "python3 -m taskplane.codex_task_executor"

[supervisor.repo_story_verifier_commands]
"owner/repo" = "python3 -m taskplane.task_verifier"

[supervisor.repo_story_force_shell_executor]
"owner/repo" = false
```

### 启动本地依赖并检查环境

```bash
taskplane-dev up
taskplane-doctor --repo owner/repo
```

## 两条推荐工作流

### 1. 三命令日常入口

如果你想用最少入口把当前仓库接入 Taskplane，优先使用：

```bash
taskplane-workflow link
taskplane-workflow intake "实现认证系统，包含 JWT 登录、刷新 token、前端登录页和权限守卫"
taskplane-workflow status
```

这条路径适合：

- 首次把仓库接入控制面
- 通过自然语言创建 proposal / review / promotion
- 快速查看当前 repo 的 blocked、running、待确认项和下一步建议

完整说明见 `docs/workflows/three-command-workflow.md`。

### 2. Session 化编排入口

如果你要持续跟踪一个 story 的运行态和 operator 介入动作，可使用：

```bash
taskplane-workflow start --repo owner/repo --story 123
taskplane-workflow watch --session <session-id>
taskplane-workflow handle --session <session-id> --approve
```

这条路径适合长链路执行、人工决策和跨轮恢复，不再把所有交互塞进单次命令里。

## 关键入口

常用但足够代表主链路的入口只有这些：

- `taskplane-dev up`
- `taskplane-doctor`
- `taskplane-workflow`
- `taskplane-supervisor`
- `taskplane-story`
- `taskplane-worker`
- `taskplane-ui`

如果你需要完整命令面，请查看 `pyproject.toml` 中的 console scripts 和 `docs/` 下的专题文档，而不是依赖 README 首页承载命令大全。

## 文档入口

建议阅读顺序：

1. `README.md`
2. `docs/README.md`
3. `docs/workflows/three-command-workflow.md`
4. `docs/architecture-overview.md`
5. `docs/substrate-architecture.md`

其他关键文档：

- `docs/product-roadmap.md`
- `docs/program-governance-model.md`
- `docs/natural-language-intake-followup-plan.md`
- `docs/agent-harness-target-architecture.md`
- `sql/MIGRATION_GUIDE.md`

## 当前状态

- 当前版本仍处于 MVP / active development 阶段。
- 仓库已经具备 PostgreSQL 控制面、自然语言 intake、story/task 执行链路、执行器路由和 operator console。
- README 首页只保留项目定位和最小上手路径；详细 API、治理策略和验证设计已下沉到 `docs/`。
- 当前仓库未提供 `LICENSE` 文件，因此不在首页声明开源许可。
