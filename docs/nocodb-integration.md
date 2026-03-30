# NocoDB 集成

## 定位

NocoDB 在这个 MVP 里只承担两类职责：

- 人类查看任务、阻塞、验证和 PR
- 在必要时对少量非真相字段做手工修正

NocoDB **不是**：

- 任务状态机
- runtime truth owner
- guardrails 执行器
- GitHub review 替代品

## 为什么需要

当前控制面已经把任务状态、依赖、验证证据和 PR 链接抽成结构化表，但数据库本身对人工排障不友好。

NocoDB 的价值是：

- 快速看 `Task Board`
- 快速看 `Blocked Queue`
- 快速看 `Verification / PR`

## 集成方式

MVP 目录已经包含：

- `ops/docker-compose.nocodb.yml`：最小 `Postgres + NocoDB` 启动配置
- `sql/control_plane_schema.sql`：控制面表结构
- `sql/nocodb_views.sql`：面向 NocoDB 的只读视图

## 启动

1. 复制环境变量样例：

```bash
cp .env.nocodb.example .env
```

2. 启动：

```bash
docker compose --env-file .env -f ops/docker-compose.nocodb.yml up -d
```

3. 打开：

```text
http://localhost:8080
```

## 建议挂载的对象

优先使用这三个 view：

- `nocodb_task_board`
- `nocodb_blocked_queue`
- `nocodb_verification_and_pr`

其次再暴露底层表：

- `work_item`
- `work_target`
- `execution_run`
- `verification_evidence`
- `pull_request_link`

## 操作边界

允许在 NocoDB 中做的事：

- 查看任务状态
- 查看冻结/owner 冲突
- 查看验证结果和 PR 链接
- 在明确授权时修正注释型字段或 review 备注

不允许在 NocoDB 中做的事：

- 手工跳过 guardrails
- 直接把 `blocked` 改成 `done`
- 修改 runtime truth 相关数据
- 让 NocoDB 反向成为任务分发真相源

## 与 GitHub 的关系

- NocoDB 负责“看板可视化”
- GitHub 负责“PR 审查与合并”
- PostgreSQL 负责“控制面状态与证据”

这三者不能混成一个状态源。
