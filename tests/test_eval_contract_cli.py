from taskplane.eval_contract_cli import main

import json

import pytest


def test_eval_contract_cli_emits_smoke_suite_manifest_json(capsys):
    exit_code = main(["--kind", "smoke-suite"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "v1"
    assert payload["kind"] == "eval_smoke_suite"
    assert payload["suite_id"] == "smoke-core"
    assert payload["scenario_ids"] == [
        "first-attempt-success",
        "retry-then-success",
        "blocked-then-escalate",
        "verify-fail-then-replan",
    ]


def test_eval_contract_cli_emits_threshold_profile_json(capsys):
    exit_code = main(["--kind", "threshold-profile"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "v1"
    assert payload["kind"] == "eval_ci_threshold_profile"
    assert payload["profile_id"] == "smoke-core-default-thresholds"
    assert payload["suite_id"] == "smoke-core"


def test_eval_contract_cli_rejects_unknown_kind():
    with pytest.raises(SystemExit):
        main(["--kind", "unknown"])
