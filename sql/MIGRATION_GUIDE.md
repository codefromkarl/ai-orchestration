# SQL 迁移说明

## 迁移文件顺序

数据库迁移应按照以下顺序应用：

1. **001_parallel_execution_extensions.sql** - 并行执行基础表
2. **002_global_coordination.sql** - 全局协调表
3. **003_ui_enhancements.sql** - UI 增强视图
4. **004_artifact_store.sql** - artifact store / executor registry / task executor mapping
5. **005_dlq_and_observability.sql** - dead letter queue / event log / observability views
6. **006_executor_routing_profiles.sql** - 多画像 executor routing 与优先级迁移
7. **007_natural_language_intake_review.sql** - natural_language_intent review / approval metadata
8. **008_repo_registry.sql** - repo 注册表，供高层 workflow `link/status` 识别仓库

`007_natural_language_intake_review.sql` 是当前 `natural_language_intent` review 字段的 forward migration，和 `sql/control_plane_schema.sql` 里的当前表结构保持一致，可用于旧库补列。

## 缺失表修复

如果数据库缺少 `001_parallel_execution_extensions.sql` 中定义的表，可以单独应用：

```bash
# 使用 psql
psql -h localhost -U stardrifter -d taskplane -f sql/apply_001.sql

# 或使用 Python
uv run python -c "
import psycopg
conn = psycopg.connect('postgresql://stardrifter:stardrifter@localhost:5432/taskplane')
with open('sql/apply_001.sql') as f:
    conn.cursor().execute(f.read())
conn.commit()
"
```

## 表依赖关系

```
001_parallel_execution_extensions.sql
├── ai_conversation_turn
├── ai_conversation_summary
├── ai_decision_log              ← 003_ui_enhancements.sql 依赖
├── notification_queue           ← 003_ui_enhancements.sql 依赖
├── agent_pool                   ← 003_ui_enhancements.sql 依赖
├── agent_execution_history      ← 003_ui_enhancements.sql 依赖
├── retry_policy
└── work_item 扩展字段

002_global_coordination.sql
├── global_execution_state
├── global_agent_pool
├── global_path_lock
└── v_global_portfolio

003_ui_enhancements.sql (依赖 001 的表)
├── v_ai_decision_history
├── v_notification_status
├── v_agent_status
├── v_agent_efficiency_stats
├── v_repo_agent_allocation
└── v_portfolio_summary

004_artifact_store.sql
├── artifact
├── executor_registry
├── task_executor_mapping
├── v_artifact_index
├── v_executor_capacity
└── v_artifact_references

005_dlq_and_observability.sql
├── dead_letter_queue
├── event_log
├── v_dlq_attention_required
├── v_recent_events
└── v_task_timeline

006_executor_routing_profiles.sql
├── task_executor_mapping.id 主键化
├── task_executor_mapping.priority
├── task_executor_mapping(task_type, priority) 索引
└── 多画像 routing seed data

007_natural_language_intake_review.sql
├── natural_language_intent.approved_at
├── natural_language_intent.approved_by
├── natural_language_intent.reviewed_at
├── natural_language_intent.reviewed_by
├── natural_language_intent.review_action
└── natural_language_intent.review_feedback

008_repo_registry.sql
├── repo_registry.repo
├── repo_registry.workdir
├── repo_registry.log_dir
└── repo_registry.updated_at
```

## 验证迁移

```bash
uv run python -c "
import psycopg
conn = psycopg.connect('postgresql://stardrifter:stardrifter@localhost:5432/taskplane')
cur = conn.cursor()
cur.execute('''
    SELECT table_name FROM information_schema.tables
    WHERE table_schema = 'public'
    ORDER BY table_name
''')
print([r[0] for r in cur.fetchall()])
"
```
