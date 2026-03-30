from __future__ import annotations

from stardrifter_orchestration_mvp.github_importer import normalize_github_issue
from stardrifter_orchestration_mvp.hierarchy_report import (
    build_hierarchy_tree,
    format_hierarchy_tree,
)


REPO = "codefromkarl/stardrifter"


def _issue(number: int, title: str, labels: list[str], body: str = "") -> object:
    return normalize_github_issue(
        REPO,
        {
            "number": number,
            "title": title,
            "body": body,
            "state": "OPEN",
            "url": f"https://github.com/{REPO}/issues/{number}",
            "labels": [{"name": lbl} for lbl in labels],
        },
    )


def _make_full_hierarchy():
    """Epic #1 -> Story #10 -> Task #100, Task #101."""
    epic = _issue(1, "Epic: Faction systems", ["epic"])
    story = _issue(10, "Story: Faction economy profile", ["story", "lane:03"], body="Part of #1.")
    task1 = _issue(100, "Task: implement trade routes", ["task", "lane:03"], body="Part of #10.")
    task2 = _issue(101, "Task: implement faction relations", ["task", "lane:03"], body="Part of #10.")
    return [epic, story, task1, task2]


def test_build_hierarchy_tree_basic_structure():
    issues = _make_full_hierarchy()
    tree = build_hierarchy_tree(issues)

    assert len(tree.epics) == 1
    epic_node = tree.epics[0]
    assert epic_node.issue_number == 1
    assert epic_node.issue_kind == "epic"

    assert len(epic_node.children) == 1
    story_node = epic_node.children[0]
    assert story_node.issue_number == 10
    assert story_node.issue_kind == "story"

    assert len(story_node.children) == 2
    task_numbers = {t.issue_number for t in story_node.children}
    assert task_numbers == {100, 101}


def test_build_hierarchy_tree_no_orphans_when_fully_linked():
    issues = _make_full_hierarchy()
    tree = build_hierarchy_tree(issues)

    assert tree.orphan_stories == []
    assert tree.orphan_tasks == []


def test_build_hierarchy_tree_orphan_story_no_epic():
    # Story with a parent reference to an issue that is not in the list
    story = _issue(10, "Story: standalone", ["story", "lane:03"], body="Part of #999.")
    task = _issue(100, "Task: do something", ["task", "lane:03"], body="Part of #10.")
    tree = build_hierarchy_tree([story, task])

    assert tree.epics == []
    assert len(tree.orphan_stories) == 1
    assert tree.orphan_stories[0].issue_number == 10
    # Task should be nested under the orphan story, not in orphan_tasks
    assert len(tree.orphan_stories[0].children) == 1
    assert tree.orphan_tasks == []


def test_build_hierarchy_tree_orphan_task_no_story():
    task = _issue(100, "Task: no parent", ["task", "lane:03"])
    tree = build_hierarchy_tree([task])

    assert tree.epics == []
    assert tree.orphan_stories == []
    assert len(tree.orphan_tasks) == 1
    assert tree.orphan_tasks[0].issue_number == 100


def test_build_hierarchy_tree_empty_input():
    tree = build_hierarchy_tree([])
    assert tree.epics == []
    assert tree.orphan_stories == []
    assert tree.orphan_tasks == []


def test_build_hierarchy_tree_epic_only():
    epic = _issue(1, "Epic: Faction systems", ["epic"])
    tree = build_hierarchy_tree([epic])
    assert len(tree.epics) == 1
    assert tree.epics[0].children == []
    assert tree.orphan_stories == []
    assert tree.orphan_tasks == []


def test_format_hierarchy_tree_contains_issue_numbers():
    issues = _make_full_hierarchy()
    tree = build_hierarchy_tree(issues)
    output = format_hierarchy_tree(tree)

    assert "#1" in output
    assert "#10" in output
    assert "#100" in output
    assert "#101" in output
    assert "Epic" in output
    assert "Story" in output
    assert "Task" in output


def test_format_hierarchy_tree_orphan_sections():
    story = _issue(10, "Orphan story", ["story", "lane:03"], body="Part of #999.")
    tree = build_hierarchy_tree([story])
    output = format_hierarchy_tree(tree)

    assert "without epic parent" in output
    assert "#10" in output


def test_format_hierarchy_tree_empty_is_empty_string():
    tree = build_hierarchy_tree([])
    output = format_hierarchy_tree(tree)
    assert output == ""
