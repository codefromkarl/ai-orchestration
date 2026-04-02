from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import GitHubNormalizedIssue


@dataclass(frozen=True)
class IssueNode:
    issue_number: int
    title: str
    issue_kind: str
    github_state: str
    status_label: str | None
    url: str
    children: list["IssueNode"] = field(default_factory=list)


@dataclass(frozen=True)
class HierarchyTree:
    epics: list[IssueNode]
    orphan_stories: list[IssueNode]
    orphan_tasks: list[IssueNode]


def build_hierarchy_tree(issues: list[GitHubNormalizedIssue]) -> HierarchyTree:
    """Build Epic -> Story -> Task hierarchy from a flat list of normalized issues."""
    by_number: dict[int, GitHubNormalizedIssue] = {i.issue_number: i for i in issues}

    def _node(issue: GitHubNormalizedIssue) -> IssueNode:
        return IssueNode(
            issue_number=issue.issue_number,
            title=issue.title,
            issue_kind=issue.issue_kind or "unknown",
            github_state=issue.github_state,
            status_label=issue.status_label,
            url=issue.url,
        )

    # Map parent -> children at each level
    stories_by_epic: dict[int, list[GitHubNormalizedIssue]] = {}
    tasks_by_story: dict[int, list[GitHubNormalizedIssue]] = {}

    for issue in issues:
        if issue.issue_kind == "story":
            for parent_num in issue.explicit_parent_issue_numbers:
                parent = by_number.get(parent_num)
                if parent and parent.issue_kind == "epic":
                    stories_by_epic.setdefault(parent_num, []).append(issue)
                    break
        elif issue.issue_kind == "task":
            for parent_num in issue.explicit_parent_issue_numbers:
                parent = by_number.get(parent_num)
                if parent and parent.issue_kind == "story":
                    tasks_by_story.setdefault(parent_num, []).append(issue)
                    break

    # Build epic nodes with nested stories -> tasks
    epic_nodes: list[IssueNode] = []
    stories_claimed: set[int] = set()
    tasks_claimed: set[int] = set()

    for issue in sorted(issues, key=lambda i: i.issue_number):
        if issue.issue_kind != "epic":
            continue
        story_children: list[IssueNode] = []
        for story in sorted(
            stories_by_epic.get(issue.issue_number, []), key=lambda i: i.issue_number
        ):
            stories_claimed.add(story.issue_number)
            task_children: list[IssueNode] = [
                _node(t)
                for t in sorted(
                    tasks_by_story.get(story.issue_number, []),
                    key=lambda i: i.issue_number,
                )
            ]
            for task in tasks_by_story.get(story.issue_number, []):
                tasks_claimed.add(task.issue_number)
            story_node = IssueNode(
                issue_number=story.issue_number,
                title=story.title,
                issue_kind="story",
                github_state=story.github_state,
                status_label=story.status_label,
                url=story.url,
                children=task_children,
            )
            story_children.append(story_node)
        epic_node = IssueNode(
            issue_number=issue.issue_number,
            title=issue.title,
            issue_kind="epic",
            github_state=issue.github_state,
            status_label=issue.status_label,
            url=issue.url,
            children=story_children,
        )
        epic_nodes.append(epic_node)

    # Orphan stories (no epic parent found)
    orphan_stories: list[IssueNode] = []
    for issue in sorted(issues, key=lambda i: i.issue_number):
        if issue.issue_kind == "story" and issue.issue_number not in stories_claimed:
            task_children = [
                _node(t)
                for t in sorted(
                    tasks_by_story.get(issue.issue_number, []),
                    key=lambda i: i.issue_number,
                )
            ]
            for task in tasks_by_story.get(issue.issue_number, []):
                tasks_claimed.add(task.issue_number)
            orphan_stories.append(
                IssueNode(
                    issue_number=issue.issue_number,
                    title=issue.title,
                    issue_kind="story",
                    github_state=issue.github_state,
                    status_label=issue.status_label,
                    url=issue.url,
                    children=task_children,
                )
            )

    # Orphan tasks (no story parent found)
    orphan_tasks: list[IssueNode] = [
        _node(issue)
        for issue in sorted(issues, key=lambda i: i.issue_number)
        if issue.issue_kind == "task" and issue.issue_number not in tasks_claimed
    ]

    return HierarchyTree(
        epics=epic_nodes,
        orphan_stories=orphan_stories,
        orphan_tasks=orphan_tasks,
    )


def format_hierarchy_tree(tree: HierarchyTree) -> str:
    """Render the hierarchy tree as indented plain text."""
    lines: list[str] = []

    def _state_badge(node: IssueNode) -> str:
        parts = [node.github_state]
        if node.status_label:
            parts.append(node.status_label)
        return " ".join(parts)

    for epic in tree.epics:
        lines.append(
            f"[Epic #{epic.issue_number}] {epic.title}  ({_state_badge(epic)})"
        )
        for story in epic.children:
            lines.append(
                f"  [Story #{story.issue_number}] {story.title}  ({_state_badge(story)})"
            )
            for task in story.children:
                lines.append(
                    f"    [Task #{task.issue_number}] {task.title}  ({_state_badge(task)})"
                )

    if tree.orphan_stories:
        lines.append("")
        lines.append("--- Stories without epic parent ---")
        for story in tree.orphan_stories:
            lines.append(
                f"  [Story #{story.issue_number}] {story.title}  ({_state_badge(story)})"
            )
            for task in story.children:
                lines.append(
                    f"    [Task #{task.issue_number}] {task.title}  ({_state_badge(task)})"
                )

    if tree.orphan_tasks:
        lines.append("")
        lines.append("--- Tasks without story parent ---")
        for task in tree.orphan_tasks:
            lines.append(
                f"  [Task #{task.issue_number}] {task.title}  ({_state_badge(task)})"
            )

    return "\n".join(lines)
