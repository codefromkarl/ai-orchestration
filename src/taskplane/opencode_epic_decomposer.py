from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row

from .contextweaver_indexing import ensure_contextweaver_index_for_checkout
from .story_decomposition import DECOMPOSITION_RESULT_MARKER


def main() -> int:
    epic_issue_number = os.environ.get("TASKPLANE_EPIC_ISSUE_NUMBER", "").strip()
    repo = (
        os.environ.get("TASKPLANE_EPIC_REPO", "").strip()
        or "codefromkarl/stardrifter"
    )
    dsn = os.environ.get("TASKPLANE_DSN", "").strip()
    project_dir = Path(
        os.environ.get("TASKPLANE_PROJECT_DIR") or Path.cwd()
    ).resolve()
    if not epic_issue_number:
        raise SystemExit("TASKPLANE_EPIC_ISSUE_NUMBER is required")
    if not dsn:
        raise SystemExit("TASKPLANE_DSN is required")

    with psycopg.connect(dsn, row_factory=cast(Any, dict_row)) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    e.issue_number,
                    e.title,
                    e.lane,
                    gin.body,
                    COALESCE(story_counts.epic_story_count, 0) AS epic_story_count
                FROM program_epic e
                LEFT JOIN github_issue_normalized gin
                  ON gin.repo = e.repo
                 AND gin.issue_number = e.issue_number
                LEFT JOIN (
                    SELECT
                        repo,
                        epic_issue_number,
                        COUNT(*) AS epic_story_count
                    FROM program_story
                    WHERE epic_issue_number IS NOT NULL
                    GROUP BY repo, epic_issue_number
                ) story_counts
                  ON story_counts.repo = e.repo
                 AND story_counts.epic_issue_number = e.issue_number
                WHERE e.repo = %s
                  AND e.issue_number = %s
                """,
                (repo, int(epic_issue_number)),
            )
            row = cur.fetchone()
    if row is None:
        raise SystemExit(f"epic not found: {epic_issue_number}")

    index_error = ensure_contextweaver_index_for_checkout(
        project_dir,
        explicit_repo=repo,
    )
    if index_error is not None:
        payload = {
            "outcome": "blocked",
            "summary": f"contextweaver index failed: {index_error}",
            "reason_code": "contextweaver-index-failed",
        }
        print(f"{DECOMPOSITION_RESULT_MARKER}{json.dumps(payload, ensure_ascii=False)}")
        return 1

    prompt = _build_prompt(
        repo=repo, row=cast(dict[str, Any], row), project_dir=project_dir
    )
    completed = subprocess.run(
        [
            "opencode",
            "run",
            "--format",
            "json",
            "--dir",
            str(project_dir),
            prompt,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=_load_timeout_seconds(),
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)

    payload = _extract_result_payload(
        (completed.stdout or "") + (completed.stderr or "")
    )
    if completed.returncode == 0 and payload.get("outcome") == "decomposed":
        try:
            created_issue_numbers = _create_story_issues_from_payload(
                repo=repo,
                epic_issue_number=int(epic_issue_number),
                epic_row=cast(dict[str, Any], row),
                payload=payload,
                project_dir=project_dir,
            )
        except ValueError as exc:
            payload = {
                "outcome": "blocked",
                "summary": str(exc),
                "reason_code": "invalid-story-payload",
            }
        except RuntimeError as exc:
            payload = {
                "outcome": "blocked",
                "summary": str(exc),
                "reason_code": "gh-issue-create-failed",
            }
        else:
            summary = str(
                payload.get("summary") or "epic decomposition completed"
            ).strip()
            payload["summary"] = (
                f"{summary}; created stories {', '.join(f'#{number}' for number in created_issue_numbers)}"
            )
            payload["created_issue_numbers"] = created_issue_numbers
    if completed.returncode != 0:
        payload = {
            "outcome": "blocked",
            "summary": payload.get("summary")
            or f"opencode exited with code {completed.returncode}",
            "reason_code": payload.get("reason_code") or "opencode-exit-nonzero",
        }
    if not payload:
        payload = {
            "outcome": "blocked",
            "summary": "opencode did not emit a valid decomposition payload",
            "reason_code": "invalid-result-payload",
        }
    print(f"{DECOMPOSITION_RESULT_MARKER}{json.dumps(payload, ensure_ascii=False)}")
    return 0


def _build_prompt(*, repo: str, row: dict, project_dir: Path) -> str:
    body = (row.get("body") or "").strip()
    return (
        f"你正在拆解 GitHub Epic #{row['issue_number']}。\n"
        f"Repo: {repo}\n"
        f"标题: {row['title']}\n"
        f"当前已投影 story 数: {row['epic_story_count']}\n"
        f"项目目录: {project_dir}\n\n"
        "先阅读 Epic 正文，以及仓库中的 AGENTS.md、CONTRIBUTING.md、execution-plan、冻结边界。\n\n"
        "你的任务只有一件事：为这个 Epic 设计 2-5 个“当前阶段最小可执行”的 Story 方案。\n\n"
        "硬规则：\n"
        "1. 不要创建 GitHub issue，不要修改文件，不要执行任何外部写操作；你只输出结构化 JSON，由控制面负责真正创建 issue。\n"
        "2. Story 必须包含明确 Scope、Goal、DoD、Boundaries 与 Candidate Tasks。\n"
        "3. 如果 Epic 明显属于实现、入库、runtime、geometry、projection、protocol、bridge、simulation、坐标系、转换或测试类工作，不得只创建 DOC Story；至少包含一个 IMPL 或 TEST 方向 Story。\n"
        "4. 如果你只能提出“需要更多信息”的建议，返回 needs_epic_refinement，不要硬拆。\n"
        "5. 不要修改 Epic 拓扑，不要创建新的 Epic。\n"
        "6. 至少创建一个挂在当前 Epic 下的合法 Story；如果做不到，必须返回 needs_epic_refinement 或 blocked，不得返回 decomposed。\n"
        "7. 你必须在本次回答中直接给出最终 JSON 结果；禁止回答‘我先去查文档/等待后台结果/稍后继续’之类的延后性内容。\n"
        "8. 最终只输出一个 JSON 对象，不要输出 Markdown 代码块。\n"
        'JSON 格式必须是 {"outcome":"decomposed|needs_epic_refinement|blocked","summary":"...","reason_code":"...","stories":[{"title":"[Story][09-A] ...","lane":"lane:09","scope":["..."],"goal":"...","dod":["..."],"boundaries":["..."],"candidate_tasks":["..."],"references":["..."]}]}。\n\n'
        f"Epic 正文如下：\n{body}\n"
    )


def _create_story_issues_from_payload(
    *,
    repo: str,
    epic_issue_number: int,
    epic_row: dict[str, Any],
    payload: dict[str, Any],
    project_dir: Path,
) -> list[int]:
    raw_stories = payload.get("stories")
    if not isinstance(raw_stories, list) or not raw_stories:
        raise ValueError("decomposed payload must include at least one story spec")
    if len(raw_stories) > 6:
        raise ValueError("decomposed payload returned more than 6 story specs")
    epic_lane = _resolve_epic_lane(epic_row)
    created_issue_numbers: list[int] = []
    for raw_story in raw_stories:
        if not isinstance(raw_story, dict):
            raise ValueError("story spec must be an object")
        title = str(raw_story.get("title") or "").strip()
        if not title:
            raise ValueError("story spec missing title")
        lane = _normalize_lane(str(raw_story.get("lane") or "").strip() or epic_lane)
        scope = _coerce_string_list(raw_story.get("scope"))
        dod = _coerce_string_list(raw_story.get("dod"))
        boundaries = _coerce_string_list(raw_story.get("boundaries"))
        candidate_tasks = _coerce_string_list(
            raw_story.get("candidate_tasks") or raw_story.get("tasks")
        )
        references = _coerce_string_list(raw_story.get("references"))
        goal = str(raw_story.get("goal") or "").strip()
        if not scope:
            raise ValueError(f"story spec missing scope: {title}")
        if not goal:
            raise ValueError(f"story spec missing goal: {title}")
        if not dod:
            raise ValueError(f"story spec missing DoD: {title}")
        if not boundaries:
            raise ValueError(f"story spec missing boundaries: {title}")
        if not candidate_tasks:
            raise ValueError(f"story spec missing candidate_tasks: {title}")
        issue_body = _render_story_issue_body(
            epic_issue_number=epic_issue_number,
            epic_title=str(epic_row.get("title") or ""),
            scope=scope,
            goal=goal,
            dod=dod,
            boundaries=boundaries,
            candidate_tasks=candidate_tasks,
            references=references,
        )
        issue_number = _create_github_issue(
            repo=repo,
            title=title,
            body=issue_body,
            labels=["story", lane, "status:pending"],
            cwd=project_dir,
        )
        created_issue_numbers.append(issue_number)
    return created_issue_numbers


def _resolve_epic_lane(epic_row: dict[str, Any]) -> str:
    lane = str(epic_row.get("lane") or "").strip()
    if lane.startswith("lane:"):
        return lane
    title = str(epic_row.get("title") or "")
    match = re.search(r"\[Epic\]\[Lane\s*(\d+)\]", title)
    if match:
        return f"lane:{match.group(1)}"
    match = re.search(r"\bLane\s*0?(\d+)\b", title)
    if match:
        return f"lane:{match.group(1)}"
    raise ValueError("epic lane is required to create story issues")


def _normalize_lane(lane: str) -> str:
    if lane.startswith("lane:"):
        return lane
    match = re.search(r"0?(\d+)", lane)
    if match:
        return f"lane:{match.group(1)}"
    return lane


def _coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            normalized.append(text)
    return normalized


def _render_story_issue_body(
    *,
    epic_issue_number: int,
    epic_title: str,
    scope: list[str],
    goal: str,
    dod: list[str],
    boundaries: list[str],
    candidate_tasks: list[str],
    references: list[str],
) -> str:
    background = f"Part of #{epic_issue_number}. ({epic_title})"
    references_block = references or [f"Epic #{epic_issue_number}"]
    return (
        "## Background\n\n"
        f"{background}\n\n"
        "## Scope\n\n"
        + "".join(f"- {item}\n" for item in scope)
        + "\n## Story Goal\n\n"
        f"{goal}\n\n"
        "## Story DoD\n\n"
        + "".join(f"- [ ] {item}\n" for item in dod)
        + "\n## Boundaries\n\n"
        + "".join(f"- {item}\n" for item in boundaries)
        + "\n## Candidate Tasks\n\n"
        + "".join(f"- {item}\n" for item in candidate_tasks)
        + "\n## References\n\n"
        + "".join(f"- {item}\n" for item in references_block)
    )


def _create_github_issue(
    *,
    repo: str,
    title: str,
    body: str,
    labels: list[str],
    cwd: Path,
) -> int:
    command = [
        "gh",
        "issue",
        "create",
        "--repo",
        repo,
        "--title",
        title,
        "--body",
        body,
    ]
    for label in labels:
        command.extend(["--label", label])
    env = os.environ.copy()
    env.pop("GITHUB_TOKEN", None)
    env.pop("GH_TOKEN", None)
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        raise RuntimeError(stderr or stdout or "gh issue create failed")
    output = f"{completed.stdout}\n{completed.stderr}"
    match = re.search(r"/issues/(\d+)", output)
    if match is None:
        raise RuntimeError("gh issue create did not return issue url")
    return int(match.group(1))


def _extract_result_payload(output: str) -> dict:
    candidates: list[str] = []
    for line in output.splitlines():
        if line.startswith(DECOMPOSITION_RESULT_MARKER):
            candidates.append(line[len(DECOMPOSITION_RESULT_MARKER) :].strip())
            continue
        stripped = line.strip()
        if not stripped.startswith("{") or not stripped.endswith("}"):
            continue
        candidates.append(stripped)
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        text_candidate = _extract_json_from_text_event(event)
        if text_candidate:
            candidates.append(text_candidate)
    for candidate in reversed(candidates):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed.get("outcome") is not None:
            return parsed
    lowered = output.lower()
    if (
        "等待后台" in output
        or "等待" in output
        and "结果" in output
        or "稍后继续" in output
        or "waiting on" in lowered
        or "waiting for" in lowered
        or "after i" in lowered
        and "continue" in lowered
    ):
        return {
            "outcome": "blocked",
            "summary": "decomposer attempted deferred/background-only reasoning instead of returning a final result",
            "reason_code": "deferred-result-not-allowed",
        }
    return {}


def _extract_json_from_text_event(event: Any) -> str | None:
    if not isinstance(event, dict) or event.get("type") != "text":
        return None
    part = event.get("part")
    if not isinstance(part, dict):
        return None
    text = part.get("text")
    if not isinstance(text, str):
        return None
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    match = re.search(r"(\{.*\})", text, re.S)
    if match:
        return match.group(1).strip()
    return None


def _load_timeout_seconds() -> int:
    raw_value = os.environ.get("TASKPLANE_OPENCODE_TIMEOUT_SECONDS", "600").strip()
    try:
        value = int(raw_value)
    except ValueError:
        return 600
    return value if value > 0 else 600


if __name__ == "__main__":
    raise SystemExit(main())
