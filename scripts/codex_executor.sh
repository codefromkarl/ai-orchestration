#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${STARDRIFTER_PROJECT_DIR:-/home/yuanzhi/Develop/playground/stardrifter}"
WORK_ID="${STARDRIFTER_WORK_ID:-unknown}"
WORK_TITLE="${STARDRIFTER_WORK_TITLE:-}"
EXECUTION_CONTEXT_JSON="${STARDRIFTER_EXECUTION_CONTEXT_JSON:-}"
EXECUTOR_TIMEOUT_SECONDS="${STARDRIFTER_EXECUTOR_TIMEOUT_SECONDS:-600}"
LOG_DIR="${STARDRIFTER_EXECUTOR_LOG_DIR:-/tmp/stardrifter-codex-exec}"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/${WORK_ID}.log"

if ! command -v codex >/dev/null 2>&1; then
  echo "codex binary not found" >&2
  exit 127
fi

snapshot_dirty_paths() {
  {
    git -C "${PROJECT_DIR}" diff --name-only --relative HEAD 2>/dev/null || true
    git -C "${PROJECT_DIR}" ls-files --others --exclude-standard 2>/dev/null || true
  } | sed '/^$/d' | LC_ALL=C sort -u
}

BEFORE_SNAPSHOT_FILE="$(mktemp)"
AFTER_SNAPSHOT_FILE="$(mktemp)"
trap 'rm -f "${BEFORE_SNAPSHOT_FILE}" "${AFTER_SNAPSHOT_FILE}"' EXIT

snapshot_dirty_paths >"${BEFORE_SNAPSHOT_FILE}"

PROMPT=$(cat <<EOF
你是仓库任务执行器，请在 ${PROJECT_DIR} 内执行任务并直接修改代码。
任务ID: ${WORK_ID}
任务标题: ${WORK_TITLE}
执行上下文(JSON, 可能为空): ${EXECUTION_CONTEXT_JSON}

要求:
1. 做最小必要修改并补充/更新对应测试。
2. 运行最小必要验证命令。
3. 禁止只做“确认”而不改代码。
EOF
)

set +e
RUST_LOG=error timeout --signal=TERM --kill-after=30 "${EXECUTOR_TIMEOUT_SECONDS}s" codex exec \
  --dangerously-bypass-approvals-and-sandbox \
  --skip-git-repo-check \
  --cd "$PROJECT_DIR" \
  "${PROMPT}" \
  >"${LOG_FILE}" 2>&1
CODEX_EXIT=$?
set -e

snapshot_dirty_paths >"${AFTER_SNAPSHOT_FILE}"

python3 - "${BEFORE_SNAPSHOT_FILE}" "${AFTER_SNAPSHOT_FILE}" "${WORK_ID}" "${CODEX_EXIT}" <<'PY'
import json
import sys
from pathlib import Path

before_file = Path(sys.argv[1])
after_file = Path(sys.argv[2])
work_id = sys.argv[3]
codex_exit = int(sys.argv[4])

before = [line.strip() for line in before_file.read_text(encoding="utf-8").splitlines() if line.strip()]
after = [line.strip() for line in after_file.read_text(encoding="utf-8").splitlines() if line.strip()]
before_set = set(before)
changed_paths = [path for path in after if path not in before_set]

if codex_exit == 0 and changed_paths:
    payload = {
        "execution_kind": "terminal",
        "outcome": "done",
        "summary": f"codex executor finished {work_id} with {len(changed_paths)} changed path(s)",
        "changed_paths": changed_paths,
        "preexisting_dirty_paths": sorted(before_set),
    }
elif codex_exit == 0:
    payload = {
        "execution_kind": "terminal",
        "outcome": "blocked",
        "reason_code": "no_effective_changes_detected",
        "summary": f"codex executor finished {work_id} but no new changed paths were detected",
        "changed_paths": [],
        "preexisting_dirty_paths": sorted(before_set),
    }
else:
    reason_code = "executor_non_zero_exit"
    if codex_exit in {124, 137}:
        reason_code = "executor_timeout"
    payload = {
        "execution_kind": "terminal",
        "outcome": "blocked",
        "reason_code": reason_code,
        "summary": f"codex executor failed for {work_id} with exit code {codex_exit}",
        "changed_paths": changed_paths,
        "preexisting_dirty_paths": sorted(before_set),
    }

print(f"STARDRIFTER_EXECUTION_RESULT_JSON={json.dumps(payload, ensure_ascii=False)}")
PY

if [[ ${CODEX_EXIT} -ne 0 ]]; then
  echo "codex executor failed for ${WORK_ID}, see ${LOG_FILE}" >&2
  tail -n 40 "${LOG_FILE}" >&2 || true
  exit ${CODEX_EXIT}
fi

echo "codex executor finished ${WORK_ID}, log=${LOG_FILE}"
