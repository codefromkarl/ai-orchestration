#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${STARDRIFTER_PROJECT_DIR:-/home/yuanzhi/Develop/playground/stardrifter}"
WORK_ID="${STARDRIFTER_WORK_ID:-unknown}"
WORK_TITLE="${STARDRIFTER_WORK_TITLE:-}"

RUST_LOG=error codex exec \
  --dangerously-bypass-approvals-and-sandbox \
  --skip-git-repo-check \
  --cd "$PROJECT_DIR" \
  "你是任务执行器。任务ID: ${WORK_ID}。标题: ${WORK_TITLE}。请基于当前仓库执行该任务，若信息不足则做最小核查并给出简短说明。"

echo "STARDRIFTER_EXECUTION_RESULT_JSON={\"execution_kind\":\"terminal\",\"outcome\":\"done\",\"summary\":\"codex executor finished ${WORK_ID}\",\"changed_paths\":[]}"
