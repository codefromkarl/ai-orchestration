# Portfolio / Execution 解耦治理模型

## 目标

本文件定义 `taskplane` 的下一阶段治理模型，用于解决以下问题：

- 新增 Epic 已经属于“整体远行星号迁移总盘子”，但不应自动混入当前执行波次
- Story / Task 的 GitHub 归属结构不稳定，直接投影到执行层会产生孤儿节点、阻塞放大和错误优先级
- 当前 PostgreSQL 控制面偏向 task execution，但还缺少 portfolio / program 层的强约束

核心目标不是提高单次 task 吞吐，而是先建立一套可审计、可分层、可逐波次激活的治理底座。

## 核心原则

### 1. 总盘子与当前波次必须解耦

同一个 Epic 可以同时满足：

- 已经属于整体迁移总树
- 当前不进入 active execution wave

因此不能再用单一 `status:pending` 语义同时表达“已批准纳入总盘子”和“当前正在排队执行”。

### 2. GitHub 是来源，不是唯一治理真相

GitHub Issue 继续承担：

- 人类阅读
- DoD / 背景 / 参考
- review / PR 审查

PostgreSQL 承担：

- 层级归属修正
- portfolio / execution 双层状态
- 依赖关系约束
- active queue 视图

### 3. 执行层只消费被激活的 Story / Task

调度器不应该直接扫描所有 task。它只能消费：

- 已进入 portfolio 总树
- 已进入当前 execution wave
- 依赖已满足
- 写集无冲突

的那一小部分 task。

## 三层模型

### Layer 1: Source Layer

仍然复用现有表：

- `github_issue_snapshot`
- `github_issue_normalized`
- `github_issue_relation`
- `github_issue_completion_audit`

职责：

- 保留 GitHub 原始内容
- 做最小归一化
- 记录 issue 标题、标签、依赖和 anomaly

### Layer 2: Governance Layer

新增治理层表，表达完整迁移总树：

- `program_epic`
- `program_story`
- `program_epic_dependency`
- `program_story_dependency`

职责：

- 定义“哪些 Epic 已属于整体迁移总盘子”
- 定义“哪些 Story 归属于哪个 Epic”
- 区分 portfolio 层状态与 execution 层状态
- 识别 orphan story / orphan task / proposed item

### Layer 3: Execution Layer

继续复用现有执行层：

- `work_item`
- `work_dependency`
- `story_dependency`
- `work_claim`

职责：

- 承载 task 级执行单元
- 计算 ready
- 管理 worktree claim
- 记录 execution / verification evidence

执行层只接收已经由 Governance Layer 激活的 Story / Task，不再自行承担 portfolio 归位职责。

## 双层状态模型

### Program Status

用于表达是否纳入整体迁移总树：

- `proposed`
- `approved`
- `completed`
- `archived`

语义：

- `proposed`: 方向已提出，但尚未正式纳入总盘子
- `approved`: 已成为整体迁移的一部分
- `completed`: 顶层范围已完成
- `archived`: 被废弃、替代或转历史

### Execution Status

用于表达是否进入当前波次：

- `backlog`
- `planned`
- `decomposing`
- `active`
- `gated`
- `done`
- `blocked`
- `needs_story_refinement`

语义：

- `backlog`: 还未进入近期执行窗口
- `planned`: 已纳入近期波次，但尚未激活
- `decomposing`: Story 已可达，但还没有形成可执行 task 容器，应先进入 AI task decomposition
- `active`: Story 已形成可执行 task，允许进入执行面
- `gated`: 属于总盘子，但被上游 Epic / Story 卡住
- `done`: 当前治理/执行范围完成
- `blocked`: 当前被明确阻塞，需治理或人决策
- `needs_story_refinement`: AI 判断 Story 边界本身失真，必须先回到治理层重构 Story

### 强约束

数据库必须保证：

- `program_status != approved` 时，不允许 `execution_status in (planned, decomposing, active)`
- `story` 没有合法 `epic` 时，不允许进入 `decomposing` / `active`
- `task` 没有合法 canonical story 时，不允许进入自动执行队列

## 当前 Epic 总树建议

以下 Epic 应并入整体迁移总树：

- `#13` Lane 01
- `#14` Lane 02
- `#15` Lane 03
- `#16` Lane 04
- `#17` Lane 05
- `#18` Lane 06
- `#19` Wave 0
- `#20` Lane INT
- `#62` Lane 07
- `#63` Lane 08
- `#64` Lane 09

其中：

- `#13-#20` 属于当前已落地的主迁移骨架
- `#62-#64` 应进入总树，但不必立即进入 active execution wave

建议初始状态：

- `#19`: `program=approved`, `execution=active`
- `#13-#18`: `program=approved`, `execution=gated`
- `#20`: `program=approved`, `execution=backlog`
- `#62-#64`: `program=approved`, `execution=planned`

## 当前 Story 归位建议

### 应补 parent Epic 的 Story

- `#65 -> #13`
- `#66 -> #14`
- `#67 -> #17`
- `#68 -> #17`

这些 Story 粒度本身是合理的，问题主要是没有合法父容器。

### 应移出当前 Story 树的项

- `#52`

`#52` 当前更像“新 lane / 新能力域规划提案”，而不是可直接纳入主线的 Story。

建议两种处理方式：

1. 升格为新的 Epic 提案
2. 保留在 GitHub，但在 PG 治理层标记为 `program=proposed`, `execution=backlog`

默认推荐：

- 不让 `#52` 继续作为 active Story 进入执行树

### Wave 0 治理项

- `#69`

`#69` 是高优先治理 task，但当前不应长期以孤儿 task 存在。

建议：

- 将其归到 `#19` 下的正式治理 Story
- 在 GitHub 未完成结构调整前，可先在 PG 中建立内部治理容器承接

## PostgreSQL 落地建议

### 建议新增类型

```sql
CREATE TYPE program_status AS ENUM (
  'proposed',
  'approved',
  'completed',
  'archived'
);

CREATE TYPE execution_status AS ENUM (
  'backlog',
  'planned',
  'decomposing',
  'active',
  'gated',
  'done',
  'blocked',
  'needs_story_refinement'
);
```

### 建议新增表

```sql
CREATE TABLE program_epic (
  issue_number INTEGER PRIMARY KEY,
  repo TEXT NOT NULL,
  title TEXT NOT NULL,
  lane TEXT,
  program_status program_status NOT NULL DEFAULT 'approved',
  execution_status execution_status NOT NULL DEFAULT 'backlog',
  active_wave TEXT,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE program_story (
  issue_number INTEGER PRIMARY KEY,
  repo TEXT NOT NULL,
  epic_issue_number INTEGER REFERENCES program_epic(issue_number),
  title TEXT NOT NULL,
  lane TEXT,
  complexity TEXT,
  program_status program_status NOT NULL DEFAULT 'approved',
  execution_status execution_status NOT NULL DEFAULT 'backlog',
  active_wave TEXT,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE program_epic_dependency (
  epic_issue_number INTEGER NOT NULL REFERENCES program_epic(issue_number) ON DELETE CASCADE,
  depends_on_epic_issue_number INTEGER NOT NULL REFERENCES program_epic(issue_number) ON DELETE CASCADE,
  PRIMARY KEY (epic_issue_number, depends_on_epic_issue_number)
);

CREATE TABLE program_story_dependency (
  story_issue_number INTEGER NOT NULL REFERENCES program_story(issue_number) ON DELETE CASCADE,
  depends_on_story_issue_number INTEGER NOT NULL REFERENCES program_story(issue_number) ON DELETE CASCADE,
  PRIMARY KEY (story_issue_number, depends_on_story_issue_number)
);
```

### 建议视图

#### 总树视图

```sql
CREATE VIEW v_program_tree AS
SELECT
  e.issue_number AS epic_issue_number,
  e.title AS epic_title,
  e.program_status AS epic_program_status,
  e.execution_status AS epic_execution_status,
  s.issue_number AS story_issue_number,
  s.title AS story_title,
  s.program_status AS story_program_status,
  s.execution_status AS story_execution_status
FROM program_epic e
LEFT JOIN program_story s
  ON s.epic_issue_number = e.issue_number;
```

#### 当前可执行 Story 视图

```sql
CREATE VIEW v_active_stories AS
SELECT s.*
FROM program_story s
JOIN program_epic e ON e.issue_number = s.epic_issue_number
WHERE e.program_status = 'approved'
  AND s.program_status = 'approved'
  AND e.execution_status = 'active'
  AND s.execution_status IN ('decomposing', 'active', 'needs_story_refinement');
```

#### 当前 task 执行队列视图

```sql
CREATE VIEW v_active_task_queue AS
SELECT wi.*
FROM work_item wi
JOIN program_story s ON s.issue_number = wi.canonical_story_issue_number
JOIN program_epic e ON e.issue_number = s.epic_issue_number
WHERE e.program_status = 'approved'
  AND s.program_status = 'approved'
  AND e.execution_status = 'active'
  AND s.execution_status = 'active';
```

#### 当前 Story 分解队列视图

```sql
CREATE VIEW v_story_decomposition_queue AS
SELECT s.*
FROM program_story s
JOIN program_epic e ON e.issue_number = s.epic_issue_number
WHERE e.program_status = 'approved'
  AND s.program_status = 'approved'
  AND e.execution_status = 'active'
  AND s.execution_status = 'decomposing';
```

## 调整顺序

### Phase A: 治理层入库

1. 建立 `program_epic` / `program_story` / dependency 表
2. 将 `#13-#20` 与 `#62-#64` 全量并入 Epic 总树
3. 赋予双层状态

### Phase B: Story 归位

1. 将 `#65/#66/#67/#68` 补 parent epic
2. 将 `#52` 标记为 `proposed`
3. 为 `#69` 建立正式治理容器
4. 对已进入当前波次但没有 task 容器的 Story，标记为 `decomposing`

### Phase C: 执行层接线

1. 调度器不再直接扫描全部 `work_item`
2. 改为只消费 `v_active_task_queue`
3. Story 分解器单独消费 `v_story_decomposition_queue`
4. 再叠加 `planned_paths + work_claim` 做并行派发

## 明确不做的事

当前阶段不做：

- 自动拆 Epic / Story
- 自动变更 GitHub 顶层结构
- 使用 pgvector 进行语义召回

先把治理树和执行树分开，再考虑更复杂的自动化能力。

## 预期结果

完成本模型后，系统将具备以下特征：

- 新增 Epic 能进入整体迁移总树，但不会自动污染当前执行波次
- Story 必须有合法父容器，孤儿节点能被数据库明确识别
- Wave 0 / Lane INT / Lane 07-09 等治理或未来波次能力，可以被明确表达为 `approved but not active`
- 执行器只消费被激活的 Story / Task，避免 portfolio 与 execution 混用
