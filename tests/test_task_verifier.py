from pathlib import Path

from stardrifter_orchestration_mvp.task_verifier import (
    _build_verifier_env,
    _extract_explicit_commands,
    _extract_pytest_targets_from_changed_paths,
    _extract_pytest_targets,
    _resolve_verification_commands,
    _should_treat_as_implementation_only_with_external_test_ownership,
    _should_treat_as_read_only_verification,
)


def test_resolve_verification_commands_returns_noop_for_doc_task(tmp_path):
    commands = _resolve_verification_commands(
        title="[01-DOC] 补充 topology 说明",
        body="## 验证方式\n\n- [ ] 文档同步\n",
        project_dir=tmp_path,
    )

    assert commands == []


def test_extract_explicit_commands_prefers_verification_section_commands():
    commands = _extract_explicit_commands(
        "## 验证方式\n\n- [ ] 运行 `python3 -m pytest -q tests/unit/test_campaign_topology_schema_closure.py`\n"
    )

    assert commands == [
        [
            "python3",
            "-m",
            "pytest",
            "-q",
            "tests/unit/test_campaign_topology_schema_closure.py",
        ]
    ]


def test_extract_pytest_targets_uses_issue_body_test_paths(tmp_path):
    tests_dir = tmp_path / "tests" / "unit"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_campaign_topology_schema_closure.py").write_text(
        "def test_ok():\n    assert True\n",
        encoding="utf-8",
    )
    (tests_dir / "test_starsector_campaign_conversion.py").write_text(
        "def test_ok():\n    assert True\n",
        encoding="utf-8",
    )

    targets = _extract_pytest_targets(
        body=(
            "## 修改范围\n\n"
            "- 允许修改：\n"
            "  - tests/unit/test_campaign_topology_schema_closure.py\n"
            "  - tests/unit/test_starsector_campaign_conversion.py\n"
            "  - docs/domains/01-campaign-topology/verification.md\n"
        ),
        project_dir=tmp_path,
    )

    assert targets == [
        "tests/unit/test_campaign_topology_schema_closure.py",
        "tests/unit/test_starsector_campaign_conversion.py",
    ]


def test_extract_pytest_targets_from_changed_paths_prefers_changed_test_files(
    tmp_path, monkeypatch
):
    tests_dir = tmp_path / "tests" / "unit"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_csv_parser.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    monkeypatch.setenv(
        "STARDRIFTER_EXECUTION_CHANGED_PATHS_JSON",
        '["tests/unit/test_csv_parser.py"]',
    )

    targets = _extract_pytest_targets_from_changed_paths(project_dir=tmp_path)

    assert targets == ["tests/unit/test_csv_parser.py"]


def test_extract_pytest_targets_from_changed_paths_infers_unit_test_from_source_path(
    tmp_path, monkeypatch
):
    tests_dir = tmp_path / "tests" / "unit"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_csv_parser.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    monkeypatch.setenv(
        "STARDRIFTER_EXECUTION_CHANGED_PATHS_JSON",
        '["src/stardrifter_engine/data_loading/csv_parser.py"]',
    )

    targets = _extract_pytest_targets_from_changed_paths(project_dir=tmp_path)

    assert targets == ["tests/unit/test_csv_parser.py"]


def test_resolve_verification_commands_falls_back_to_focused_pytest_targets(tmp_path):
    tests_dir = tmp_path / "tests" / "unit"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_campaign_topology_schema_closure.py").write_text(
        "def test_ok():\n    assert True\n",
        encoding="utf-8",
    )

    commands = _resolve_verification_commands(
        title="[01-TEST] 补强 stable location references 一致性验证",
        body=(
            "## 修改范围\n\n"
            "- 允许修改：\n"
            "  - tests/unit/test_campaign_topology_schema_closure.py\n"
            "  - src/stardrifter_engine/campaign/authoring_conversion.py\n\n"
            "## 验证方式\n\n"
            "- [ ] 运行 stable location references 相关 focused 测试\n"
        ),
        project_dir=tmp_path,
    )

    assert commands == [
        [
            "python3",
            "-m",
            "pytest",
            "-q",
            "tests/unit/test_campaign_topology_schema_closure.py",
        ]
    ]


def test_build_verifier_env_prepends_src_to_pythonpath(tmp_path, monkeypatch):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    monkeypatch.setenv("PYTHONPATH", "/existing/path")

    env = _build_verifier_env(tmp_path)

    assert env["PYTHONPATH"] == f"{src_dir}:/existing/path"


def test_build_verifier_env_keeps_existing_pythonpath_when_src_missing(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PYTHONPATH", "/existing/path")

    env = _build_verifier_env(tmp_path)

    assert env["PYTHONPATH"] == "/existing/path"


def test_resolve_verification_commands_returns_noop_for_read_only_godot_scope(tmp_path):
    commands = _resolve_verification_commands(
        title="[05-IMPL] Expose minimal ship HUD snapshot fields for ship_id hp and position",
        body=(
            "## 修改范围\n\n"
            "- 允许修改：\n"
            "  - godot/ships/scripts/ship.gd\n"
            "  - godot/ships/resources/*.gd\n\n"
            "## 验证方式\n\n"
            "- [ ] Read-based contract check confirms the snapshot method includes ship_id/hp/position fields.\n"
            "- [ ] Snapshot-shape changes are confined to the allowlisted Godot ship/resource files.\n"
            "- [ ] No changes are made under docs/authority, docs/data-schema, src/stardrifter_engine/projections, or godot/strategic_map.\n"
        ),
        project_dir=tmp_path,
    )

    assert commands == []


def test_should_treat_as_read_only_verification_rejects_python_source_scope():
    result = _should_treat_as_read_only_verification(
        body=(
            "## 修改范围\n\n"
            "- 允许修改：\n"
            "  - src/stardrifter_engine/bridge/router.py\n\n"
            "## 验证方式\n\n"
            "- [ ] Read-based contract check confirms router wiring.\n"
        )
    )

    assert result is False


def test_resolve_verification_commands_returns_noop_for_impl_task_with_external_test_ownership(
    tmp_path,
):
    commands = _resolve_verification_commands(
        title="[09B-IMPL] implement combat adapter command dispatch and payload mapping",
        body=(
            "## 修改范围\n\n"
            "- 允许修改：\n"
            "  - godot/bridge/adapters/combat_adapter.gd\n"
            "  - godot/bridge/command_bridge.gd\n"
            "  - src/stardrifter_engine/models/protocol.py\n\n"
            "## 验证方式\n\n"
            "- [ ] Manual/code read confirms modifications stay confined to the allowlisted adapter/router/protocol files.\n"
            "- [ ] Focused test coverage for combat bridge command routing and query_state behavior is owned by #194, not this implementation task.\n"
            "- [ ] No changes are made under tests/ or unrelated Fleet/Campaign/Data bridge paths.\n"
        ),
        project_dir=tmp_path,
    )

    assert commands == []


def test_should_treat_as_implementation_only_with_external_test_ownership_detects_marker():
    result = _should_treat_as_implementation_only_with_external_test_ownership(
        body=(
            "## 修改范围\n\n"
            "- 允许修改：\n"
            "  - src/stardrifter_engine/models/protocol.py\n"
            "  - tests/unit/test_godot_combat_bridge_contract.py\n\n"
            "## 验证方式\n\n"
            "- [ ] Focused test coverage for combat bridge command routing is owned by #194, not this implementation task.\n"
        )
    )

    assert result is True
