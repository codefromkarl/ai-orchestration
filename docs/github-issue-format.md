# GitHub Issue 格式规范

本规范的目标不是美观，而是让：

- GitHub issue 可被 AI 稳定读取
- PostgreSQL importer 可稳定抽取 parent / lane / complexity / DoD
- NocoDB / 控制面能做低歧义展示

## 总原则

1. 标题只承担 `kind + lane/wave + 对象`，不要把父级关系藏在标题里。
2. parent 关系必须写在专用章节，不能散落在 `参考` 或 `备注`。
3. `参考` 里的 issue 编号默认不会被 importer 当作 parent。
4. 一个 issue 如果有多个 parent candidate，必须明确写 `开放问题`，不要假装是单父。
5. 所有 task 必须带 `complexity:*` 标签。
6. 所有可执行 task / story 必须带 `lane:*` 标签；process issue 单独标记，不混入 lane execution tree。

## 标题格式

### Epic

```text
[Epic][Lane 03] Economy & Markets 迁移
[Epic][Wave 0] Freeze 基线锁定
```

### Story

```text
[Story][03-C] Faction economy profile
[Story][06-D] Verification closure
```

### Task

```text
[03-DOC] 为 03-C 三条开放项补充 wave 标记与后续 task 跟踪
[02-IMPL] fleet logistics/crew/cargo runtime 骨架实现
```

## Parent 抽取规则

importer 只从以下位置抽取 parent：

- `Part of #xx`
- `## 上级 Story`
- `## 上级 Epic`

不会从以下位置抽 parent：

- `## 参考`
- `## 备注`
- `## Candidate Tasks`
- 普通正文里的相关 issue 编号

## 必填章节

### Epic 必填

- `## Background`
- `## Strategic Goal`
- `## Success Criteria`
- `## Scope`
- `## References`

### Story 必填

- `## Background`
- `Part of #<epic-number>` 或 `## 上级 Epic`
- `## Scope`
- `## Story Goal`
- `## Story DoD`
- `## Boundaries`
- `## Candidate Tasks`
- `## References`

### Task 必填

- `## 背景`
- `## 上级 Story`
- `## 目标`
- `## 修改范围`
- `## 验收标准 (DoD)`
- `## 验证方式`
- `## 参考`

## Parent 写法示例

### 单父 Story

```markdown
## 上级 Story

- #29
```

### 单父 Epic

```markdown
Part of #19.
```

### 多父候选

```markdown
## 上级 Story

- #24
- #25
- #26

## 备注

当前是多父候选，导入 PostgreSQL 后必须人工确定 canonical parent。
```

## 标签规范

### Epic

- `epic`
- `status:*`
- `lane:*` 或 Wave 容器专用标签

### Story

- `story`
- `status:*`
- `lane:*`

### Task

- `task`
- `status:*`
- `lane:*`
- `complexity:low|medium|high`

## 明确禁止

- 在 `参考` 段落里假装写 parent
- 只写“上级 Story：待补充”但不写 issue 号
- task 不打 `complexity:*`
- process/governance issue 冒充 lane task
- 一个 issue 同时混合 Epic/Story/Task 语义
