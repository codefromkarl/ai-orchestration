from __future__ import annotations

import json
import os
from pathlib import Path
import re

from .execution_protocol import EXECUTION_RESULT_MARKER


def main() -> int:
    project_dir = Path(os.environ.get("TASKPLANE_PROJECT_DIR") or Path.cwd()).resolve()
    work_id = (os.environ.get("TASKPLANE_WORK_ID") or "taskplane-demo").strip()
    title = (os.environ.get("TASKPLANE_WORK_TITLE") or "Taskplane demo task").strip()
    target_relative_path = _choose_target_relative_path(
        project_dir=project_dir,
        work_id=work_id,
        title=title,
        execution_context_raw=os.environ.get("TASKPLANE_EXECUTION_CONTEXT_JSON", ""),
    )
    target_path = project_dir / target_relative_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        _build_demo_content(work_id=work_id, title=title),
        encoding="utf-8",
    )

    payload = {
        "outcome": "done",
        "summary": f"demo executor wrote {target_relative_path}",
        "changed_paths": [str(target_relative_path).replace("\\", "/")],
        "preexisting_dirty_paths": [],
    }
    print(f"{EXECUTION_RESULT_MARKER}{json.dumps(payload, ensure_ascii=False)}")
    return 0


def _choose_target_relative_path(
    *,
    project_dir: Path,
    work_id: str,
    title: str,
    execution_context_raw: str,
) -> Path:
    planned_paths = _extract_planned_paths(execution_context_raw)
    if planned_paths:
        first = planned_paths[0].strip()
        if first.endswith("/"):
            return Path(first) / f"taskplane_demo_{_slugify(work_id)}.md"
        suffix = Path(first).suffix
        if suffix:
            target = Path(first)
            return target.with_name(
                f"{target.stem}_taskplane_demo_{_slugify(work_id)}{target.suffix}"
            )
        return Path(first) / f"taskplane_demo_{_slugify(work_id)}.md"
    return Path("examples") / "taskplane-demo" / f"{_slugify(work_id)}.md"


def _extract_planned_paths(execution_context_raw: str) -> list[str]:
    if not execution_context_raw.strip():
        return []
    try:
        payload = json.loads(execution_context_raw)
    except json.JSONDecodeError:
        return []
    planned_paths = payload.get("planned_paths")
    if not isinstance(planned_paths, list):
        return []
    return [str(item) for item in planned_paths if str(item).strip()]


def _build_demo_content(*, work_id: str, title: str) -> str:
    return (
        f"# Taskplane Demo Output\n\n"
        f"- work_id: `{work_id}`\n"
        f"- title: {title}\n"
        f"- generated_by: `taskplane.demo_task_executor`\n"
    )


def _slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-") or "taskplane-demo"


if __name__ == "__main__":
    raise SystemExit(main())
