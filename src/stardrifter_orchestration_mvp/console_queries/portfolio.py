LIST_PORTFOLIO_SUMMARY_QUERY = """
SELECT * FROM v_portfolio_summary
ORDER BY operator_attention_required DESC, repo
"""

LIST_AI_DECISIONS_QUERY = """
SELECT * FROM v_ai_decision_history
ORDER BY created_at DESC
LIMIT %s
"""

LIST_AI_DECISIONS_WITH_REPO_QUERY = """
SELECT * FROM v_ai_decision_history
WHERE repo = %s
ORDER BY created_at DESC
LIMIT %s
"""

LIST_NOTIFICATIONS_SENT_QUERY = """
SELECT * FROM v_notification_status
ORDER BY created_at DESC
LIMIT %s
"""

LIST_NOTIFICATIONS_PENDING_QUERY = """
SELECT * FROM v_pending_notifications_detailed
ORDER BY created_at DESC
LIMIT %s
"""

LIST_NOTIFICATIONS_WITH_REPO_SENT_QUERY = """
SELECT * FROM v_notification_status
WHERE repo = %s
ORDER BY created_at DESC
LIMIT %s
"""

LIST_NOTIFICATIONS_WITH_REPO_PENDING_QUERY = """
SELECT * FROM v_pending_notifications_detailed
WHERE repo = %s
ORDER BY created_at DESC
LIMIT %s
"""

LIST_AGENT_STATUS_QUERY = """
SELECT * FROM v_agent_status
ORDER BY status, agent_name
"""

LIST_AGENT_STATUS_WITH_REPO_QUERY = """
SELECT * FROM v_agent_status
WHERE assigned_repo = %s OR base_quota_repo = %s
ORDER BY status, agent_name
"""

GET_FAILED_NOTIFICATIONS_QUERY = """
SELECT * FROM v_failed_notifications
ORDER BY last_attempt_at DESC
"""

GET_FAILED_NOTIFICATIONS_WITH_REPO_QUERY = """
SELECT * FROM v_failed_notifications
WHERE repo = %s
ORDER BY last_attempt_at DESC
"""

GET_AGENT_EFFICIENCY_STATS_QUERY = """
SELECT * FROM v_agent_efficiency_stats
ORDER BY total_executions DESC
"""
