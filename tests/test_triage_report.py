from stardrifter_orchestration_mvp.github_importer import (
    build_completion_audit,
    extract_relation_candidates,
    normalize_github_issue,
)
from stardrifter_orchestration_mvp.issue_projection import project_github_tasks_to_work_items
from stardrifter_orchestration_mvp.triage_report import build_triage_report


def test_build_triage_report_reports_unprojected_tasks_and_empty_story():
    issues = [
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 29,
                "title": "[Story][03-C] Faction economy profile",
                "body": "Part of #15.",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/29",
                "labels": [{"name": "story"}, {"name": "lane:03"}],
            },
        ),
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 60,
                "title": "[PROCESS] 建立人机协作开发规范",
                "body": "## 背景\n\nprocess work.\n",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/60",
                "labels": [{"name": "task"}, {"name": "status:in-progress"}],
            },
        ),
    ]
    relations = []
    for issue in issues:
        relations.extend(extract_relation_candidates(issue))
    audit = build_completion_audit(issues, relations)
    projection = project_github_tasks_to_work_items(
        issues=issues,
        relations=relations,
        completion_audit=audit,
    )

    report = build_triage_report(
        issues=issues,
        relations=relations,
        completion_audit=audit,
        projection=projection,
    )

    assert report.unprojected_task_issue_numbers == [60]
    assert report.storys_without_projected_tasks == [29]
    assert report.anomalies_by_issue[60] == ["missing-lane"]
