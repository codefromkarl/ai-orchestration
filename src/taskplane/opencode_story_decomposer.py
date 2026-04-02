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

from .models import TaskSpecDraft
from .repository import PostgresControlPlaneRepository
from .contextweaver_indexing import ensure_contextweaver_index_for_checkout
from .execution_protocol import (
    EXECUTION_CHECKPOINT_MARKER,
    EXECUTION_WAIT_MARKER,
)
from .story_decomposition import DECOMPOSITION_RESULT_MARKER


def main() -> int:
    story_issue_number = os.environ.get("TASKPLANE_STORY_ISSUE_NUMBER", "").strip()
    repo = (
        os.environ.get("TASKPLANE_STORY_REPO", "").strip()
        or "codefromkarl/stardrifter"
    )
    dsn = os.environ.get("TASKPLANE_DSN", "").strip()
    project_dir = Path(
        os.environ.get("TASKPLANE_PROJECT_DIR") or Path.cwd()
    ).resolve()
    if not story_issue_number:
        raise SystemExit("TASKPLANE_STORY_ISSUE_NUMBER is required")
    if not dsn:
        raise SystemExit("TASKPLANE_DSN is required")

    conn = psycopg.connect(dsn, row_factory=cast(Any, dict_row))
    try:
        repository = PostgresControlPlaneRepository(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    s.issue_number,
                    s.title,
                    s.lane,
                    gin.body,
                    COALESCE(task_counts.story_task_count, 0) AS story_task_count
                FROM program_story s
                LEFT JOIN github_issue_normalized gin
                  ON gin.repo = s.repo
                 AND gin.issue_number = s.issue_number
                LEFT JOIN (
                    SELECT
                        repo,
                        canonical_story_issue_number AS story_issue_number,
                        COUNT(*) AS story_task_count
                    FROM work_item
                    WHERE canonical_story_issue_number IS NOT NULL
                    GROUP BY repo, canonical_story_issue_number
                ) task_counts
                  ON task_counts.repo = s.repo
                 AND task_counts.story_issue_number = s.issue_number
                WHERE s.repo = %s
                  AND s.issue_number = %s
                """,
                (repo, int(story_issue_number)),
            )
            row = cur.fetchone()
        if row is None:
            raise SystemExit(f"story not found: {story_issue_number}")

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
            print(
                f"{DECOMPOSITION_RESULT_MARKER}{json.dumps(payload, ensure_ascii=False)}"
            )
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
                created_issue_numbers = _create_task_issues_from_payload(
                    repo=repo,
                    story_issue_number=int(story_issue_number),
                    story_row=cast(dict[str, Any], row),
                    payload=payload,
                    project_dir=project_dir,
                    repository=repository,
                )
            except ValueError as exc:
                payload = {
                    "outcome": "blocked",
                    "summary": str(exc),
                    "reason_code": "invalid-task-payload",
                }
            except RuntimeError as exc:
                payload = {
                    "outcome": "blocked",
                    "summary": str(exc),
                    "reason_code": "gh-issue-create-failed",
                }
            else:
                summary = str(
                    payload.get("summary") or "story decomposition completed"
                ).strip()
                payload["summary"] = (
                    f"{summary}; created tasks {', '.join(f'#{number}' for number in created_issue_numbers)}"
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
        kind = str(payload.get("execution_kind") or "").strip().lower()
        if kind == "checkpoint":
            marker = EXECUTION_CHECKPOINT_MARKER
        elif kind == "wait":
            marker = EXECUTION_WAIT_MARKER
        else:
            marker = DECOMPOSITION_RESULT_MARKER
        print(f"{marker}{json.dumps(payload, ensure_ascii=False)}")
        return 0
    finally:
        conn.close()


def _build_prompt(*, repo: str, row: dict, project_dir: Path) -> str:
    body = (row.get("body") or "").strip()
    return (
        f"你正在拆解 GitHub Story #{row['issue_number']}。\n"
        f"Repo: {repo}\n"
        f"标题: {row['title']}\n"
        f"当前已投影 task 数: {row['story_task_count']}\n"
        f"项目目录: {project_dir}\n\n"
        "先阅读 Story 正文，以及仓库中的 AGENTS.md、CONTRIBUTING.md、execution-plan、冻结边界。\n\n"
        "你的任务只有一件事：为这个 Story 设计 2-4 个“当前阶段最小可执行”的 Task 方案。\n\n"
        "硬规则：\n"
        "1. 不要创建 GitHub issue，不要修改文件，不要执行任何外部写操作；你只输出结构化 JSON，由控制面负责真正创建 issue。\n"
        "2. 如果 Story 明显属于实现、入库、runtime、geometry、projection、protocol、bridge、simulation、坐标系、转换或测试类工作，不得只创建 DOC task；至少包含一个 IMPL 或 TEST task。\n"
        "3. 如果你只能拆出文档澄清任务，而无法指出任何代码或测试落点，返回 needs_story_refinement，不要硬拆。\n"
        "4. 不要修改 Epic/Story 拓扑，不要创建新 Epic。\n"
        "5. 所有 Task 方案必须能直接映射到合法 Task issue：标题、复杂度、目标、允许修改路径、DoD、验证方式、参考都要给出。\n"
        "6. 至少创建一个挂在当前 Story 下的合法 Task；如果做不到，必须返回 needs_story_refinement 或 blocked，不得返回 decomposed。\n"
        "7. Story 正文里的 `Candidate Tasks` 编号只可当历史线索，不能当成当前已存在任务；是否已有任务只以“当前已投影 task 数”为准。如果当前已投影 task 数为 0，你必须创建新的 Task，或返回 needs_story_refinement / blocked。\n"
        "8. 验证方式（verification）必须用自然语言描述验证目标，禁止写具体的 pytest 命令（如 `python3 -m pytest -q tests/unit/`）。正确示例：'确认 CSV 解析容错功能通过 focused 单测'。验证器会根据变更的文件自动推断要跑的测试。\n"
        "9. 你可以输出两种 JSON：\n"
        "   - 终态 JSON（terminal）：outcome 为 decomposed/needs_story_refinement/blocked，附带 task 列表\n"
        '     格式: {"outcome":"decomposed|needs_story_refinement|blocked","summary":"...","reason_code":"...","tasks":[...]}\n'
        "   - 检查点 JSON（checkpoint）：用于分步完成时暂存进度\n"
        '     格式: {"execution_kind":"checkpoint","phase":"researching","summary":"...","artifacts":{},"next_action_hint":"继续生成 task"}\n'
        "   - 等待 JSON（wait）：当需要等待外部条件或子结果时使用\n"
        '     格式: {"execution_kind":"wait","wait_type":"subagent_result","summary":"...","resume_hint":"..."}\n'
        "10. 最终只输出一个 JSON 对象，不要输出 Markdown 代码块。\n"
        'JSON 格式必须是 {"outcome":"decomposed|needs_story_refinement|blocked","summary":"...","reason_code":"...","tasks":[{"title":"[01-IMPL] ...","complexity":"low|medium|high","goal":"...","allowed_paths":["..."],"dod":["..."],"verification":["..."],"references":["..."]}]}。\n\n'
        f"Story 正文如下：\n{body}\n"
    )


def _create_task_issues_from_payload(
    *,
    repo: str,
    story_issue_number: int,
    story_row: dict[str, Any],
    payload: dict[str, Any],
    project_dir: Path,
    repository: Any | None = None,
) -> list[int]:
    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ValueError("decomposed payload must include at least one task spec")
    if len(raw_tasks) > 4:
        raise ValueError("decomposed payload returned more than 4 task specs")
    lane = _resolve_story_lane(story_row)
    created_issue_numbers: list[int] = []
    for raw_task in raw_tasks:
        if not isinstance(raw_task, dict):
            raise ValueError("task spec must be an object")
        title = str(raw_task.get("title") or "").strip()
        if not title:
            raise ValueError("task spec missing title")
        complexity = _normalize_complexity(raw_task.get("complexity"))
        allowed_paths = _coerce_string_list(
            raw_task.get("allowed_paths") or raw_task.get("paths")
        )
        dod = _coerce_string_list(raw_task.get("dod"))
        verification = _coerce_string_list(raw_task.get("verification"))
        references = _coerce_string_list(raw_task.get("references"))
        goal = str(raw_task.get("goal") or "").strip()
        if not goal:
            raise ValueError(f"task spec missing goal: {title}")
        if not allowed_paths:
            raise ValueError(f"task spec missing allowed_paths: {title}")
        if not dod:
            raise ValueError(f"task spec missing DoD: {title}")
        if not verification:
            raise ValueError(f"task spec missing verification: {title}")
        if repository is not None and hasattr(repository, "record_task_spec_draft"):
            repository.record_task_spec_draft(
                TaskSpecDraft(
                    repo=repo,
                    story_issue_number=story_issue_number,
                    title=title,
                    complexity=complexity,
                    goal=goal,
                    allowed_paths=tuple(allowed_paths),
                    dod=tuple(dod),
                    verification=tuple(verification),
                    references=tuple(references),
                    source_reason_code=str(payload.get("reason_code") or "") or None,
                )
            )
        issue_body = _render_task_issue_body(
            story_issue_number=story_issue_number,
            story_title=str(story_row.get("title") or ""),
            goal=goal,
            allowed_paths=allowed_paths,
            dod=dod,
            verification=verification,
            references=references,
        )
        issue_number = _create_github_issue(
            repo=repo,
            title=title,
            body=issue_body,
            labels=["task", lane, f"complexity:{complexity}", "status:pending"],
            cwd=project_dir,
        )
        created_issue_numbers.append(issue_number)
    return created_issue_numbers


def _resolve_story_lane(story_row: dict[str, Any]) -> str:
    lane = str(story_row.get("lane") or "").strip()
    if lane.startswith("lane:"):
        return lane
    title = str(story_row.get("title") or "")
    match = re.search(r"\[Story\]\[(\d+)-", title)
    if match:
        return f"lane:{match.group(1)}"
    raise ValueError("story lane is required to create task issues")


def _normalize_complexity(value: Any) -> str:
    complexity = str(value or "").strip().lower()
    if complexity in {"low", "medium", "high"}:
        return complexity
    return "medium"


def _coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            normalized.append(text)
    return normalized


def _render_task_issue_body(
    *,
    story_issue_number: int,
    story_title: str,
    goal: str,
    allowed_paths: list[str],
    dod: list[str],
    verification: list[str],
    references: list[str],
) -> str:
    background = f"拆自 Story #{story_issue_number}：{story_title}"
    references_block = references or [f"Story #{story_issue_number}"]
    return (
        "## 背景\n\n"
        f"{background}\n\n"
        "## 上级 Story\n\n"
        f"- #{story_issue_number}\n\n"
        "## 目标\n\n"
        f"{goal}\n\n"
        "## 修改范围\n\n"
        "- 允许修改：\n"
        + "".join(f"  - {path}\n" for path in allowed_paths)
        + "- 禁止修改：\n"
        + "  - 超出上述路径以及 Story Boundaries 明确禁止的区域\n\n"
        + "## 验收标准 (DoD)\n\n"
        + "".join(f"- [ ] {item}\n" for item in dod)
        + "\n## 验证方式\n\n"
        + "".join(f"- [ ] {item}\n" for item in verification)
        + "\n## 参考\n\n"
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
        if not isinstance(parsed, dict):
            continue
        kind = str(parsed.get("execution_kind") or "").strip().lower()
        if kind in {"checkpoint", "wait", "retry_intent"}:
            return parsed
        if parsed.get("outcome") is not None:
            return parsed
    lowered = output.lower()
    if (
        "等待后台" in output
        or ("等待" in output and "结果" in output)
        or "稍后继续" in output
        or "waiting on" in lowered
        or "waiting for" in lowered
        or ("after i" in lowered and "continue" in lowered)
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
