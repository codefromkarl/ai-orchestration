# SQL 迁移说明

## 迁移文件顺序

数据库迁移应按照以下顺序应用：

1. **001_parallel_execution_extensions.sql** - 并行执行基础表
2. **002_global_coordination.sql** - 全局协调表
3. **003_ui_enhancements.sql** - UI 增强视图

## 缺失表修复

如果数据库缺少 `001_parallel_execution_extensions.sql` 中定义的表，可以单独应用：

```bash
# 使用 psql
psql -h localhost -U stardrifter -d stardrifter_orchestration -f sql/apply_001.sql

# 或使用 Python
uv run python -c "
import psycopg
conn = psycopg.connect('postgresql://stardrifter:stardrifter@localhost:5432/stardrifter_orchestration')
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
```

## 验证迁移

```bash
uv run python -c "
import psycopg
conn = psycopg.connect('postgresql://stardrifter:stardrifter@localhost:5432/stardrifter_orchestration')
cur = conn.cursor()
cur.execute('''
    SELECT table_name FROM information_schema.tables
    WHERE table_schema = 'public'
    ORDER BY table_name
''')
print([r[0] for r in cur.fetchall()])
"
```
