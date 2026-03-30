from stardrifter_orchestration_mvp.models import WorkItem
from stardrifter_orchestration_mvp.story_runner import load_story_work_item_ids


class FakeRepository:
    def __init__(self, work_items):
        self._work_items = work_items

    def list_work_items(self):
        return list(self._work_items)


def test_load_story_work_item_ids_filters_by_story_issue_number():
    repository = FakeRepository(
        [
            WorkItem(
                id="issue-56",
                title="task 56",
                lane="Lane 03",
                wave="wave-2",
                status="done",
                source_issue_number=56,
                story_issue_numbers=(29,),
            ),
            WorkItem(
                id="issue-57",
                title="task 57",
                lane="Lane 03",
                wave="wave-2",
                status="pending",
                source_issue_number=57,
                story_issue_numbers=(29,),
            ),
            WorkItem(
                id="issue-44",
                title="task 44",
                lane="Lane 01",
                wave="wave-1",
                status="in_progress",
                source_issue_number=44,
                story_issue_numbers=(21, 22, 23),
            ),
        ]
    )

    assert load_story_work_item_ids(repository=repository, story_issue_number=29) == [
        "issue-56",
        "issue-57",
    ]
