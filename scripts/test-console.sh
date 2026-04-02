#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

MODE="${1:-all}"

if [[ "$MODE" != "unit" && "$MODE" != "integration" && "$MODE" != "smoke" && "$MODE" != "all" ]]; then
  printf 'Usage: %s [unit|integration|smoke|all]\n' "$0" >&2
  exit 1
fi

run_unit() {
  printf '\n[console-tests] unit\n'
  node --test "tests/test_console_helpers.mjs"
  python3 -m pytest -q tests/test_console_actions.py tests/test_hierarchy_api_actions.py
}

run_integration() {
  printf '\n[console-tests] integration\n'
  : "${TASKPLANE_TEST_POSTGRES_DSN:?TASKPLANE_TEST_POSTGRES_DSN is required for integration tests}"
  python3 -m pytest -q tests/test_console_read_api.py tests/test_hierarchy_api_actions.py
}

run_smoke() {
  printf '\n[console-tests] smoke\n'
  : "${TASKPLANE_TEST_POSTGRES_DSN:?TASKPLANE_TEST_POSTGRES_DSN is required for smoke tests}"
  python3 -m pytest -q tests/smoke_console_ui.py
}

case "$MODE" in
  unit)
    run_unit
    ;;
  integration)
    run_unit
    run_integration
    ;;
  smoke)
    run_smoke
    ;;
  all)
    run_unit
    run_integration
    run_smoke
    ;;
esac
