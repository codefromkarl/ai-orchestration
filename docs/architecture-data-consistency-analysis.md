# 数据不一致问题架构分析与修复建议

## 一、问题根本原因

### 1. 数据流入点设计缺陷 (issue_projection.py:71-86)

WorkItem 创建时 repo 字段由外部参数传入，而非从关联的 program_story 继承：

```python
# issue_projection.py:71
work_item = WorkItem(
    id=work_item_id,
    repo=None,  # ← 没有设置，依赖 projection_sync.py 传入
    wave="unassigned",  # ← 硬编码
    ...
)
```

### 2. 投影同步覆盖风险 (projection_sync.py:91-123)

ON CONFLICT DO UPDATE 会覆盖 repo 字段：

```sql
ON CONFLICT (id) DO UPDATE SET
    repo = EXCLUDED.repo,  -- 每次同步都可能改变
    ...
```

### 3. 延迟校验架构缺陷

| 校验点 | 校验类型 | 问题 |
|--------|----------|------|
| sync_ready_states | 写入时 (修复后) | 原设计无完整性检查 |
| v_active_task_queue | 查询时 | JOIN 排除不匹配，但不修复 |
| Guardrails | 运行时 | 问题爆发点，用户看到错误 |

### 4. 数据库约束缺失

work_item 表没有任何 CHECK、FOREIGN KEY 或 NOT NULL 约束来保证：
- repo 与 canonical_story_issue_number 的一致性
- wave 与 parent Epic/Story 的一致性

### 5. 数据流向问题

```
数据流向：GitHub → Import → Sync → Dispatch → Execute
                ↓         ↓         ↓          ↓
            问题引入   问题累积   问题隐藏    问题爆发
```

## 二、架构修复方案（按优先级排序）

### 【优先级 1】数据库触发器自动修复（推荐）

在数据库层面保证数据一致性，无需修改应用代码：

```sql
-- 触发器 1: 自动继承 repo 从 program_story
CREATE OR REPLACE FUNCTION trg_inherit_work_item_repo()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.repo IS NULL AND NEW.canonical_story_issue_number IS NOT NULL THEN
        SELECT ps.repo INTO NEW.repo
        FROM program_story ps
        WHERE ps.issue_number = NEW.canonical_story_issue_number;

        IF NEW.repo IS NULL THEN
            RAISE EXCEPTION 'Cannot inherit repo: story #% does not exist',
                NEW.canonical_story_issue_number;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_inherit_work_item_repo_before_insert
    BEFORE INSERT ON work_item
    FOR EACH ROW
    EXECUTE FUNCTION trg_inherit_work_item_repo();

-- 触发器 2: 自动继承 wave 从 parent Epic
CREATE OR REPLACE FUNCTION trg_inherit_work_item_wave()
RETURNS TRIGGER AS $$
DECLARE
    v_epic_wave TEXT;
BEGIN
    IF NEW.wave IS NULL OR NEW.wave = 'unassigned' THEN
        SELECT pe.active_wave INTO v_epic_wave
        FROM program_story ps
        JOIN program_epic pe ON pe.issue_number = ps.epic_issue_number
        WHERE ps.issue_number = NEW.canonical_story_issue_number;

        IF v_epic_wave IS NOT NULL THEN
            NEW.wave := v_epic_wave;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_inherit_work_item_wave_before_insert
    BEFORE INSERT OR UPDATE ON work_item
    FOR EACH ROW
    EXECUTE FUNCTION trg_inherit_work_item_wave();
```

**优点:**
- 应用层无需修改
- 数据流入点自动修复
- 保证最终一致性

### 【优先级 2】增强 sync_ready_states 自动修复能力

在状态同步时自动修复数据问题，而非仅阻塞：

```python
def sync_ready_states(self) -> None:
    with self._connection.cursor() as cursor:
        # 新增：自动修复 repo 字段
        cursor.execute("""
            UPDATE work_item wi
            SET repo = ps.repo
            FROM program_story ps
            WHERE wi.canonical_story_issue_number = ps.issue_number
              AND wi.repo IS NULL
              AND ps.repo IS NOT NULL
        """)

        # 新增：自动修复 wave 字段
        cursor.execute("""
            UPDATE work_item wi
            SET wave = COALESCE(ps.active_wave, pe.active_wave, 'Wave0')
            FROM program_story ps
            JOIN program_epic pe ON pe.issue_number = ps.epic_issue_number
            WHERE wi.canonical_story_issue_number = ps.issue_number
              AND (wi.wave IS NULL OR wi.wave = 'unassigned')
        """)

        # 原有的完整性阻塞逻辑...
```

### 【优先级 3】修改 issue_projection.py 强制设置 repo

在数据创建源头保证完整性：

```python
# issue_projection.py:51-86
def project_github_tasks_to_work_items(...) -> GitHubTaskProjection:
    issue_by_number = {issue.issue_number: issue for issue in issues}

    # 预加载 story 的 repo 映射
    story_repo_map = {
        issue.issue_number: issue.repo
        for issue in issues
        if issue.issue_kind == "story" and issue.repo is not None
    }

    for issue in issues:
        if issue.issue_kind != "task":
            continue

        # 从关联的 story 继承 repo
        repo = story_repo_map.get(canonical_story_issue_number)

        work_item = WorkItem(
            id=work_item_id,
            repo=repo,  # ← 强制设置
            wave=issue.wave or "unassigned",  # ← 从 issue 继承
            ...
        )
```

### 【优先级 4】添加数据库约束（最后一步）

在数据质量稳定后添加严格约束：

```sql
-- 添加 NOT NULL 约束
ALTER TABLE work_item
    ALTER COLUMN repo SET NOT NULL
    WHERE canonical_story_issue_number IS NOT NULL;

-- 添加 CHECK 约束
ALTER TABLE work_item
    ADD CONSTRAINT chk_work_item_wave_not_null
    CHECK (wave IS NOT NULL);

-- 添加 FOREIGN KEY 约束
ALTER TABLE work_item
    ADD CONSTRAINT fk_work_item_canonical_story
    FOREIGN KEY (canonical_story_issue_number, repo)
    REFERENCES program_story(issue_number, repo);
```

## 三、已应用的修复（当前状态）

### 1. 数据完整性视图
- `v_work_item_integrity_check` - 识别缺失字段的工作项
- `v_wave_consistency_check` - 识别 Wave 不一致的工作项
- `v_orphan_work_items` - 识别孤立工作项
- `v_active_task_queue_strict` - 更严格的活跃任务队列视图

### 2. 数据库函数
- `validate_work_item_ready()` - 在状态变更时验证数据完整性
- `repair_work_item_data()` - 自动修复常见数据问题

### 3. 数据库触发器（已完成）
- `trg_inherit_work_item_repo()` - INSERT 时自动继承 repo
- `trg_inherit_work_item_wave()` - INSERT/UPDATE 时自动继承 wave
- `trg_sync_repo_on_story_change()` - story 变更时同步 repo
- `trg_validate_work_item_integrity()` - INSERT/UPDATE 时验证完整性
- `backfill_work_item_integrity()` - 修复现有数据的辅助函数

### 4. 应用层修复
- `repository.py:sync_ready_states()` - **增强自动修复能力**
  - Step 2: 自动修复缺失的 repo 字段
  - Step 3: 自动修复缺失/unassigned 的 wave 字段
  - Step 4: 对无法修复的数据进行阻塞
- `supervisor_loop.py:_build_story_command()` - 添加 `--allowed-wave Wave0` 参数

### 5. 数据修复执行
- 修复 21 个 orphan work items 的 repo 字段
- 修复 2 个独立任务的 repo 字段 (issue-47, issue-74)
- 设置 Lane 05 Epic #17 和 Stories #33-37 的 `active_wave='Wave0'`

## 四、推荐的下一步行动

### 1. 已完成：应用优先级 1 的数据库触发器
- [x] 保证新数据的完整性
- [x] 无需修改应用代码
- [x] 执行 `sql/data_integrity_triggers.sql` 中的触发器定义

### 2. 已完成：增强 sync_ready_states 自动修复
- [x] 每次轮询时自动修复问题数据
- [x] 减少手动干预
- [x] 修复逻辑集成到 repository.py:sync_ready_states()

### 3. 已完成：修改 issue_projection.py（数据源头强制设置）
- [x] 在数据源头强制设置 repo 字段
- [x] 从 canonical story 继承 repo
- [x] wave 字段由数据库触发器继承

### 4. 长期：添加数据库约束
- 在数据质量稳定后
- 添加严格约束保证一致性
- 建议先观察触发器运行效果
