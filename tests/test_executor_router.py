from unittest.mock import MagicMock, patch

from taskplane.executor_router import (
    ExecutorConfig,
    ExecutorMapping,
    ExecutorRouter,
)
from taskplane.models import ExecutionContext, WorkItem


def _mock_connect(mock_connect, fetchall_result=None):
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    if fetchall_result is not None:
        mock_cursor.fetchall.return_value = fetchall_result
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    mock_connect.return_value = mock_conn
    return mock_conn, mock_cursor


def test_executor_router_selects_preferred():
    with patch(
        "taskplane.executor_router.psycopg.connect"
    ) as mock_connect:

        class FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def cursor(self):
                c = MagicMock()
                c.__enter__ = MagicMock(return_value=c)
                c.__exit__ = MagicMock(return_value=False)
                c.fetchall.side_effect = [
                    [
                        {
                            "task_type": "core_path",
                            "preferred_executor": "claude-code",
                            "fallback_executor": "opencode",
                            "conditions": {},
                        }
                    ],
                    [
                        {
                            "executor_name": "claude-code",
                            "executor_type": "agent_cli",
                            "capabilities": ["code_edit"],
                            "max_concurrent": 4,
                            "is_active": True,
                            "metadata": {},
                        },
                        {
                            "executor_name": "opencode",
                            "executor_type": "agent_cli",
                            "capabilities": ["code_edit"],
                            "max_concurrent": 4,
                            "is_active": True,
                            "metadata": {},
                        },
                    ],
                ]
                return c

        mock_connect.return_value = FakeConn()

        router = ExecutorRouter(dsn="postgresql://fake:fake@localhost/fake")
        executor = router.select_executor("core_path")

        assert executor is not None
        assert executor.executor_name == "claude-code"


def test_executor_router_falls_back_when_preferred_inactive():
    with patch(
        "taskplane.executor_router.psycopg.connect"
    ) as mock_connect:

        class FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def cursor(self):
                c = MagicMock()
                c.__enter__ = MagicMock(return_value=c)
                c.__exit__ = MagicMock(return_value=False)
                c.fetchall.side_effect = [
                    [
                        {
                            "task_type": "core_path",
                            "preferred_executor": "claude-code",
                            "fallback_executor": "opencode",
                            "conditions": {},
                        }
                    ],
                    [
                        {
                            "executor_name": "claude-code",
                            "executor_type": "agent_cli",
                            "capabilities": [],
                            "max_concurrent": 4,
                            "is_active": False,
                            "metadata": {},
                        },
                        {
                            "executor_name": "opencode",
                            "executor_type": "agent_cli",
                            "capabilities": [],
                            "max_concurrent": 4,
                            "is_active": True,
                            "metadata": {},
                        },
                    ],
                ]
                return c

        mock_connect.return_value = FakeConn()

        router = ExecutorRouter(dsn="postgresql://fake:fake@localhost/fake")
        executor = router.select_executor("core_path")

        assert executor is not None
        assert executor.executor_name == "opencode"


def test_executor_router_returns_none_when_no_mapping():
    with patch(
        "taskplane.executor_router.psycopg.connect"
    ) as mock_connect:

        class FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def cursor(self):
                c = MagicMock()
                c.__enter__ = MagicMock(return_value=c)
                c.__exit__ = MagicMock(return_value=False)
                c.fetchall.side_effect = [
                    [
                        {
                            "task_type": "core_path",
                            "preferred_executor": "claude-code",
                            "fallback_executor": None,
                            "conditions": {},
                        }
                    ],
                    [
                        {
                            "executor_name": "claude-code",
                            "executor_type": "agent_cli",
                            "capabilities": [],
                            "max_concurrent": 4,
                            "is_active": True,
                            "metadata": {},
                        }
                    ],
                ]
                return c

        mock_connect.return_value = FakeConn()

        router = ExecutorRouter(dsn="postgresql://fake:fake@localhost/fake")
        executor = router.select_executor("unknown_type")

        assert executor is not None
        assert executor.executor_name == "claude-code"


def test_executor_router_uses_configured_default_for_unknown_type():
    with patch(
        "taskplane.executor_router.psycopg.connect"
    ) as mock_connect:

        class FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def cursor(self):
                c = MagicMock()
                c.__enter__ = MagicMock(return_value=c)
                c.__exit__ = MagicMock(return_value=False)
                c.fetchall.side_effect = [
                    [],
                    [
                        {
                            "executor_name": "codex",
                            "executor_type": "agent_cli",
                            "capabilities": [],
                            "max_concurrent": 2,
                            "is_active": True,
                            "metadata": {},
                        },
                        {
                            "executor_name": "claude-code",
                            "executor_type": "agent_cli",
                            "capabilities": [],
                            "max_concurrent": 4,
                            "is_active": True,
                            "metadata": {},
                        },
                    ],
                ]
                return c

        mock_connect.return_value = FakeConn()

        router = ExecutorRouter(
            dsn="postgresql://fake:fake@localhost/fake",
            default_executor_name="codex",
        )
        executor = router.select_executor("unknown_type")

        assert executor is not None
        assert executor.executor_name == "codex"


def test_executor_router_returns_first_active_when_default_missing():
    with patch(
        "taskplane.executor_router.psycopg.connect"
    ) as mock_connect:

        class FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def cursor(self):
                c = MagicMock()
                c.__enter__ = MagicMock(return_value=c)
                c.__exit__ = MagicMock(return_value=False)
                c.fetchall.side_effect = [
                    [],
                    [
                        {
                            "executor_name": "shell",
                            "executor_type": "shell",
                            "capabilities": ["bash"],
                            "max_concurrent": 8,
                            "is_active": True,
                            "metadata": {},
                        },
                        {
                            "executor_name": "browser",
                            "executor_type": "browser",
                            "capabilities": ["navigate"],
                            "max_concurrent": 2,
                            "is_active": True,
                            "metadata": {},
                        },
                    ],
                ]
                return c

        mock_connect.return_value = FakeConn()

        router = ExecutorRouter(
            dsn="postgresql://fake:fake@localhost/fake",
            default_executor_name="missing-default",
        )
        executor = router.select_executor("unknown_type")

        assert executor is not None
        assert executor.executor_name == "shell"


def test_executor_router_list_executors():
    with patch(
        "taskplane.executor_router.psycopg.connect"
    ) as mock_connect:

        class FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def cursor(self):
                c = MagicMock()
                c.__enter__ = MagicMock(return_value=c)
                c.__exit__ = MagicMock(return_value=False)
                c.fetchall.side_effect = [
                    [],
                    [
                        {
                            "executor_name": "claude-code",
                            "executor_type": "agent_cli",
                            "capabilities": ["code_edit"],
                            "max_concurrent": 4,
                            "is_active": True,
                            "metadata": {},
                        }
                    ],
                ]
                return c

        mock_connect.return_value = FakeConn()

        router = ExecutorRouter(dsn="postgresql://fake:fake@localhost/fake")
        executors = router.list_executors()

        assert len(executors) == 1
        assert executors[0].executor_name == "claude-code"


def test_executor_router_list_mappings():
    with patch(
        "taskplane.executor_router.psycopg.connect"
    ) as mock_connect:

        class FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def cursor(self):
                c = MagicMock()
                c.__enter__ = MagicMock(return_value=c)
                c.__exit__ = MagicMock(return_value=False)
                c.fetchall.side_effect = [
                    [
                        {
                            "task_type": "core_path",
                            "preferred_executor": "claude-code",
                            "fallback_executor": "opencode",
                            "conditions": {},
                        }
                    ],
                    [],
                ]
                return c

        mock_connect.return_value = FakeConn()

        router = ExecutorRouter(dsn="postgresql://fake:fake@localhost/fake")
        mappings = router.list_mappings()

        assert len(mappings) == 1
        assert mappings[0].task_type == "core_path"
        assert mappings[0].fallback_executor == "opencode"


def test_executor_router_prefers_failure_history_specific_mapping():
    with patch("taskplane.executor_router.psycopg.connect") as mock_connect:

        class FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def cursor(self):
                c = MagicMock()
                c.__enter__ = MagicMock(return_value=c)
                c.__exit__ = MagicMock(return_value=False)
                c.fetchall.side_effect = [
                    [
                        {
                            "task_type": "core_path",
                            "preferred_executor": "recovery-agent",
                            "fallback_executor": "opencode",
                            "conditions": {
                                "min_attempt_count": 2,
                                "last_failure_reasons": ["timeout"],
                            },
                        },
                        {
                            "task_type": "core_path",
                            "preferred_executor": "default-agent",
                            "fallback_executor": "opencode",
                            "conditions": {},
                        },
                    ],
                    [
                        {
                            "executor_name": "recovery-agent",
                            "executor_type": "agent_cli",
                            "capabilities": ["resume_retry"],
                            "max_concurrent": 2,
                            "is_active": True,
                            "metadata": {},
                        },
                        {
                            "executor_name": "default-agent",
                            "executor_type": "agent_cli",
                            "capabilities": ["code_edit"],
                            "max_concurrent": 4,
                            "is_active": True,
                            "metadata": {},
                        },
                        {
                            "executor_name": "opencode",
                            "executor_type": "agent_cli",
                            "capabilities": ["code_edit"],
                            "max_concurrent": 4,
                            "is_active": True,
                            "metadata": {},
                        },
                    ],
                ]
                return c

        mock_connect.return_value = FakeConn()

        router = ExecutorRouter(dsn="postgresql://fake:fake@localhost/fake")
        executor = router.select_executor(
            "core_path",
            work_item=WorkItem(
                id="task-301",
                title="[09-IMPL] retry timed out executor",
                lane="Lane 09",
                wave="Wave0",
                status="ready",
                task_type="core_path",
                attempt_count=2,
                last_failure_reason="timeout",
            ),
            execution_context=ExecutionContext(
                work_id="task-301",
                title="retry timed out executor",
                lane="Lane 09",
                wave="Wave0",
                resume_hint="resume_candidate",
            ),
        )

        assert executor is not None
        assert executor.executor_name == "recovery-agent"


def test_executor_router_prefers_task_profile_specific_mapping():
    with patch("taskplane.executor_router.psycopg.connect") as mock_connect:

        class FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def cursor(self):
                c = MagicMock()
                c.__enter__ = MagicMock(return_value=c)
                c.__exit__ = MagicMock(return_value=False)
                c.fetchall.side_effect = [
                    [
                        {
                            "task_type": "core_path",
                            "preferred_executor": "frontend-agent",
                            "fallback_executor": "opencode",
                            "conditions": {
                                "planned_path_prefixes": ["frontend/"],
                                "title_keywords": ["ui", "console"],
                                "requires_story_workspace": True,
                            },
                        },
                        {
                            "task_type": "core_path",
                            "preferred_executor": "default-agent",
                            "fallback_executor": "opencode",
                            "conditions": {},
                        },
                    ],
                    [
                        {
                            "executor_name": "frontend-agent",
                            "executor_type": "agent_cli",
                            "capabilities": ["ui_edit"],
                            "max_concurrent": 2,
                            "is_active": True,
                            "metadata": {},
                        },
                        {
                            "executor_name": "default-agent",
                            "executor_type": "agent_cli",
                            "capabilities": ["code_edit"],
                            "max_concurrent": 4,
                            "is_active": True,
                            "metadata": {},
                        },
                        {
                            "executor_name": "opencode",
                            "executor_type": "agent_cli",
                            "capabilities": ["code_edit"],
                            "max_concurrent": 4,
                            "is_active": True,
                            "metadata": {},
                        },
                    ],
                ]
                return c

        mock_connect.return_value = FakeConn()

        router = ExecutorRouter(dsn="postgresql://fake:fake@localhost/fake")
        executor = router.select_executor(
            "core_path",
            work_item=WorkItem(
                id="task-302",
                title="[09-UI] Story console polish",
                lane="Lane 09",
                wave="Wave0",
                status="ready",
                task_type="core_path",
                canonical_story_issue_number=42,
                planned_paths=("frontend/src/components/WorkspacePanel.tsx",),
            ),
        )

        assert executor is not None
        assert executor.executor_name == "frontend-agent"


def test_executor_router_prefers_historical_failure_mapping_from_execution_runs_and_dlq():
    with patch("taskplane.executor_router.psycopg.connect") as mock_connect:

        class InitConn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def cursor(self):
                c = MagicMock()
                c.__enter__ = MagicMock(return_value=c)
                c.__exit__ = MagicMock(return_value=False)
                c.fetchall.side_effect = [
                    [
                        {
                            "task_type": "core_path",
                            "preferred_executor": "recovery-agent",
                            "fallback_executor": "opencode",
                            "conditions": {
                                "historical_failure_reasons": [
                                    "git-lock-conflict",
                                    "timeout",
                                ],
                                "min_historical_failures": 2,
                            },
                        },
                        {
                            "task_type": "core_path",
                            "preferred_executor": "default-agent",
                            "fallback_executor": "opencode",
                            "conditions": {},
                        },
                    ],
                    [
                        {
                            "executor_name": "recovery-agent",
                            "executor_type": "agent_cli",
                            "capabilities": ["resume_retry"],
                            "max_concurrent": 2,
                            "is_active": True,
                            "metadata": {},
                        },
                        {
                            "executor_name": "default-agent",
                            "executor_type": "agent_cli",
                            "capabilities": ["code_edit"],
                            "max_concurrent": 4,
                            "is_active": True,
                            "metadata": {},
                        },
                        {
                            "executor_name": "opencode",
                            "executor_type": "agent_cli",
                            "capabilities": ["code_edit"],
                            "max_concurrent": 4,
                            "is_active": True,
                            "metadata": {},
                        },
                    ],
                ]
                return c

        class HistoryConn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def cursor(self):
                c = MagicMock()
                c.__enter__ = MagicMock(return_value=c)
                c.__exit__ = MagicMock(return_value=False)

                def execute(sql, params):
                    del params
                    c._last_sql = sql

                def fetchall():
                    if "FROM execution_run" in c._last_sql:
                        return [
                            {"reason_code": "git-lock-conflict"},
                            {"reason_code": "timeout"},
                        ]
                    if "FROM dead_letter_queue" in c._last_sql:
                        return [{"failure_reason": "timeout"}]
                    return []

                c.execute.side_effect = execute
                c.fetchall.side_effect = fetchall
                return c

        mock_connect.side_effect = [InitConn(), HistoryConn()]

        router = ExecutorRouter(dsn="postgresql://fake:fake@localhost/fake")
        executor = router.select_executor(
            "core_path",
            work_item=WorkItem(
                id="task-303",
                title="[09-IMPL] retry after git lock",
                lane="Lane 09",
                wave="Wave0",
                status="ready",
                task_type="core_path",
            ),
        )

        assert executor is not None
        assert executor.executor_name == "recovery-agent"


def test_executor_router_prefers_higher_priority_mapping_when_scores_tie():
    with patch("taskplane.executor_router.psycopg.connect") as mock_connect:

        class FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def cursor(self):
                c = MagicMock()
                c.__enter__ = MagicMock(return_value=c)
                c.__exit__ = MagicMock(return_value=False)
                c.fetchall.side_effect = [
                    [
                        {
                            "id": 1,
                            "task_type": "core_path",
                            "priority": 100,
                            "preferred_executor": "default-agent",
                            "fallback_executor": "opencode",
                            "conditions": {"title_keywords": ["ui"]},
                        },
                        {
                            "id": 2,
                            "task_type": "core_path",
                            "priority": 300,
                            "preferred_executor": "frontend-agent",
                            "fallback_executor": "opencode",
                            "conditions": {"title_keywords": ["ui"]},
                        },
                    ],
                    [
                        {
                            "executor_name": "frontend-agent",
                            "executor_type": "agent_cli",
                            "capabilities": ["ui_edit"],
                            "max_concurrent": 2,
                            "is_active": True,
                            "metadata": {},
                        },
                        {
                            "executor_name": "default-agent",
                            "executor_type": "agent_cli",
                            "capabilities": ["code_edit"],
                            "max_concurrent": 4,
                            "is_active": True,
                            "metadata": {},
                        },
                        {
                            "executor_name": "opencode",
                            "executor_type": "agent_cli",
                            "capabilities": ["code_edit"],
                            "max_concurrent": 4,
                            "is_active": True,
                            "metadata": {},
                        },
                    ],
                ]
                return c

        mock_connect.return_value = FakeConn()

        router = ExecutorRouter(dsn="postgresql://fake:fake@localhost/fake")
        executor = router.select_executor(
            "core_path",
            work_item=WorkItem(
                id="task-304",
                title="[09-UI] polish drawer",
                lane="Lane 09",
                wave="Wave0",
                status="ready",
                task_type="core_path",
            ),
        )

        assert executor is not None
        assert executor.executor_name == "frontend-agent"
