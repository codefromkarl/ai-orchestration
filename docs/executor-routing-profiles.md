# Executor Routing Profiles

> 最后更新：2026-04-02

本文档描述 `task_executor_mapping.conditions` 支持的画像路由字段，以及当前推荐的默认配置思路。

## 1. 目标

把 executor 选择从“按 `task_type` 固定映射”升级成“按失败历史 + 任务画像路由”。

当前实现支持：

- 同一 `task_type` 多条 mapping
- `priority` 决定同分匹配时的优先级
- `execution_run` / `dead_letter_queue` 历史失败信号
- `planned_paths` / `title_keywords` / story 归属 / `resume_hint`
- `executor_selected` 事件落到 `event_log`

## 2. 条件字段

`conditions` 是 JSONB，当前支持这些键：

- `min_attempt_count`
- `max_attempt_count`
- `last_failure_reasons`
- `recent_failure_reasons`
- `dlq_failure_reasons`
- `historical_failure_reasons`
- `min_historical_failures`
- `max_historical_failures`
- `exclude_failure_reasons`
- `planned_path_prefixes`
- `title_keywords`
- `requires_story_workspace`
- `complexities`
- `lanes`
- `waves`
- `resume_hints`

说明：

- `last_failure_reasons` 匹配 `work_item.last_failure_reason`
- `recent_failure_reasons` 来自最近 `execution_run.status='blocked'` 的 `result_payload_json.reason_code`
- `dlq_failure_reasons` 来自 `dead_letter_queue.failure_reason`
- `historical_failure_reasons` 是 recent + dlq 的去重并集
- `min_historical_failures` / `max_historical_failures` 看 recent + dlq 总次数
- `title_keywords` 采用全部关键词都命中
- `planned_path_prefixes` 采用任一路径前缀命中

## 3. 推荐策略

### 3.1 恢复型重试

适合：

- `timeout`
- `git-lock-conflict`
- `interrupted_retryable`
- 有 `resume_candidate`

推荐 executor：

- `codex`
- fallback: `opencode`

推荐 priority：

- `300`

### 3.2 前端 / Story 共用 workspace

适合：

- `frontend/` 目录
- 标题命中 `ui`
- 带 `canonical_story_issue_number`

推荐 executor：

- `gemini-cli`
- fallback: `claude-code`

推荐 priority：

- `250`

### 3.3 默认 core_path

适合：

- 其余 `core_path`

推荐 executor：

- `claude-code`
- fallback: `opencode`

推荐 priority：

- `100`

## 4. 观测入口

SQL / 视图：

- `v_executor_routing_profiles`
- `v_executor_selection_events`

API：

- `GET /api/executors/routing`
- `GET /api/repos/{repo}/executor-selections`

## 5. 直接检查

```sql
SELECT * FROM v_executor_routing_profiles;
SELECT * FROM v_executor_selection_events WHERE repo = 'codefromkarl/stardrifter' LIMIT 50;
```
