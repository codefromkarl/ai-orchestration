from __future__ import annotations

from stardrifter_orchestration_mvp import console_queries


def test_console_queries_exports_stable_public_query_constants() -> None:
    public_names = {
        name
        for name in vars(console_queries)
        if name.endswith("_QUERY") and name.isupper()
    }

    assert public_names
    assert console_queries.__all__ == sorted(public_names)

    for name in console_queries.__all__:
        value = getattr(console_queries, name)
        assert isinstance(value, str)
        assert value.strip()

    assert console_queries.LIST_REPOSITORIES_QUERY
    assert console_queries.GET_REPO_SUMMARY_QUERY
    assert console_queries.LIST_RUNNING_JOBS_QUERY
    assert console_queries.GET_JOB_DETAIL_QUERY
    assert console_queries.LIST_EPIC_ROWS_QUERY
    assert console_queries.LIST_EPIC_ROWS_FALLBACK_QUERY
    assert console_queries.LIST_EPIC_STORY_TREE_QUERY
    assert console_queries.GET_EPIC_DETAIL_QUERY
    assert console_queries.GET_STORY_DETAIL_QUERY
    assert console_queries.GET_TASK_DETAIL_QUERY
    assert console_queries.LIST_PORTFOLIO_SUMMARY_QUERY
    assert console_queries.GET_STATUS_COUNTS_EXECUTION_QUERY
    assert console_queries.GET_STATUS_COUNTS_STATUS_QUERY
    assert console_queries.REQUIRE_REPO_QUERY
