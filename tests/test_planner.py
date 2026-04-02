from taskplane.models import WorkDependency, WorkItem
from taskplane.planner import derive_ready_work_ids


def test_derive_ready_work_ids_only_returns_pending_items_with_completed_dependencies():
    work_items = [
        WorkItem(id="task-1", title="already done", lane="Lane 01", wave="wave-1", status="done"),
        WorkItem(id="task-2", title="root ready", lane="Lane 01", wave="wave-1", status="pending"),
        WorkItem(id="task-3", title="blocked by task-2", lane="Lane 01", wave="wave-1", status="pending"),
        WorkItem(id="task-4", title="already running", lane="Lane 01", wave="wave-1", status="in_progress"),
        WorkItem(id="task-5", title="blocked by running task", lane="Lane 01", wave="wave-1", status="pending"),
    ]
    dependencies = [
        WorkDependency(work_id="task-3", depends_on_work_id="task-2"),
        WorkDependency(work_id="task-5", depends_on_work_id="task-4"),
    ]

    ready_ids = derive_ready_work_ids(work_items, dependencies)

    assert ready_ids == {"task-2"}


def test_derive_ready_work_ids_ignores_story_dependencies_within_same_multi_parent_cluster():
    work_items = [
        WorkItem(
            id="issue-44",
            title="story 21/22/23 precursor",
            lane="Lane 01",
            wave="wave-1",
            status="done",
            story_issue_numbers=(21, 22, 23),
        ),
        WorkItem(
            id="issue-47",
            title="story 24/25/26 root task",
            lane="Lane 02",
            wave="wave-2",
            status="pending",
            story_issue_numbers=(24, 25, 26),
        ),
    ]
    ready_ids = derive_ready_work_ids(
        work_items,
        [],
        story_dependencies=[(24, 23), (25, 24), (26, 25)],
    )

    assert ready_ids == {"issue-47"}


def test_derive_ready_work_ids_ignores_soft_blocker_dependencies():
    work_items = [
        WorkItem(
            id="issue-53",
            title="[04-DOC] cross-cutting note",
            lane="Lane 04",
            wave="unassigned",
            status="pending",
            canonical_story_issue_number=30,
            task_type="documentation",
            blocking_mode="soft",
        ),
        WorkItem(
            id="issue-54",
            title="[04-DOC] downstream task",
            lane="Lane 04",
            wave="unassigned",
            status="pending",
            canonical_story_issue_number=30,
        ),
    ]
    dependencies = [
        WorkDependency(work_id="issue-54", depends_on_work_id="issue-53"),
    ]

    ready_ids = derive_ready_work_ids(work_items, dependencies)

    assert ready_ids == {"issue-53", "issue-54"}
