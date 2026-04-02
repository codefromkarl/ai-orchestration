from __future__ import annotations

import os
import subprocess
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

import pytest
import psycopg
from playwright.sync_api import sync_playwright


PORT = 8024
BASE_URL = f"http://127.0.0.1:{PORT}"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _required_env(repo: str) -> dict[str, str]:
    dsn = os.getenv("TASKPLANE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("TASKPLANE_TEST_POSTGRES_DSN is required for smoke UI test")
    assert dsn is not None
    return {
        "TASKPLANE_DSN": dsn,
        "TASKPLANE_CONSOLE_REPO_WORKDIRS_JSON": f'{{"{repo}":"{REPO_ROOT}"}}',
        "TASKPLANE_CONSOLE_REPO_LOG_DIRS_JSON": f'{{"{repo}":"/tmp/taskplane-console-logs"}}',
    }


def _seed_smoke_repo(dsn: str, repo: str) -> str:
    work_id = f"issue-{uuid4().hex[:8]}"
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE epic_execution_state
                    ADD COLUMN IF NOT EXISTS verification_status TEXT,
                    ADD COLUMN IF NOT EXISTS verification_reason_code TEXT,
                    ADD COLUMN IF NOT EXISTS last_verification_at TIMESTAMPTZ,
                    ADD COLUMN IF NOT EXISTS verification_summary TEXT
                """
            )
            cursor.execute(
                """
                INSERT INTO program_epic (
                    repo, issue_number, title, lane, program_status, execution_status, active_wave, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    301,
                    "Smoke Epic",
                    "Lane smoke",
                    "approved",
                    "active",
                    "wave-smoke",
                    None,
                ),
            )
            cursor.execute(
                """
                INSERT INTO program_story (
                    repo, issue_number, epic_issue_number, title, lane, complexity,
                    program_status, execution_status, active_wave, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    302,
                    301,
                    "Smoke Story",
                    "Lane smoke",
                    "medium",
                    "approved",
                    "active",
                    "wave-smoke",
                    None,
                ),
            )
            cursor.execute(
                """
                INSERT INTO epic_execution_state (
                    repo, epic_issue_number, status,
                    completed_story_issue_numbers_json,
                    blocked_story_issue_numbers_json,
                    remaining_story_issue_numbers_json,
                    verification_status,
                    verification_reason_code,
                    verification_summary
                ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s)
                ON CONFLICT (repo, epic_issue_number) DO UPDATE SET
                    status = EXCLUDED.status,
                    completed_story_issue_numbers_json = EXCLUDED.completed_story_issue_numbers_json,
                    blocked_story_issue_numbers_json = EXCLUDED.blocked_story_issue_numbers_json,
                    remaining_story_issue_numbers_json = EXCLUDED.remaining_story_issue_numbers_json,
                    verification_status = EXCLUDED.verification_status,
                    verification_reason_code = EXCLUDED.verification_reason_code,
                    verification_summary = EXCLUDED.verification_summary,
                    updated_at = NOW()
                """,
                (
                    repo,
                    301,
                    "awaiting_operator",
                    "[]",
                    "[302]",
                    "[]",
                    "failed",
                    "epic_verification_failed",
                    "epic verification failed",
                ),
            )
            cursor.execute(
                """
                INSERT INTO work_item (
                    id, repo, title, lane, wave, status, complexity,
                    source_issue_number, canonical_story_issue_number,
                    task_type, blocking_mode, dod_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    work_id,
                    repo,
                    "Smoke Task",
                    "Lane smoke",
                    "wave-smoke",
                    "ready",
                    "low",
                    44,
                    302,
                    "documentation",
                    "soft",
                    '{"planned_paths": ["docs/smoke.md"]}',
                ),
            )
        connection.commit()
    return work_id


def _wait_for_server(url: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"server did not start in time: {last_error}")


def _assert_console_landing_ready(page) -> None:
    assert page.locator("#repo-input").is_visible()
    assert page.locator("#load-console-btn").is_visible()
    assert page.locator("#summary-title").is_visible()
    assert page.locator("#summary-title").inner_text().strip() != ""

    _assert_console_has_no_stray_overlay_or_menu(page)

    assert page.locator("#detail-drawer").get_attribute("aria-hidden") == "true"
    assert page.locator("#workspace-panel").is_hidden()


def _assert_console_has_no_stray_overlay_or_menu(page) -> None:
    confirmation_modal = page.locator("#confirmation-modal")
    assert confirmation_modal.get_attribute("aria-hidden") == "true"
    assert confirmation_modal.is_hidden()

    issue_card_menu = page.locator(".issue-card__menu").first
    if issue_card_menu.count() > 0:
        assert issue_card_menu.is_hidden()


@pytest.mark.integration
def test_console_smoke_flow():
    repo = f"codefromkarl/stardrifter-smoke-{uuid4().hex[:8]}"
    dsn = os.getenv("TASKPLANE_TEST_POSTGRES_DSN")
    assert dsn is not None
    work_id = _seed_smoke_repo(dsn, repo)

    env = os.environ.copy()
    env.update(_required_env(repo))
    log_path = Path("/tmp/stardrifter-ui-smoke-8024.log")
    with log_path.open("w", encoding="utf-8") as handle:
        server = subprocess.Popen(
            [
                "python3",
                "-m",
                "taskplane.hierarchy_api_cli",
                "--host",
                "127.0.0.1",
                "--port",
                str(PORT),
            ],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
    try:
        _wait_for_server(f"{BASE_URL}/console")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{BASE_URL}/console")
            page.wait_for_function(
                "() => document.querySelector('#repo-input') && document.querySelector('#summary-title')",
                timeout=10000,
            )
            page.wait_for_timeout(500)
            _assert_console_landing_ready(page)
            page.select_option("#repo-input", repo)
            page.click("#load-console-btn")
            page.wait_for_function(
                f"() => document.querySelector('#summary-title')?.textContent?.includes('{repo}')",
                timeout=10000,
            )

            page.wait_for_function(
                '() => document.querySelector("#app-nav") && document.querySelector("[data-nav-l1=\\"overview\\"]") && document.querySelector("[data-nav-l1=\\"detail\\"]")',
                timeout=10000,
            )
            page.wait_for_function(
                "() => document.querySelectorAll('#nav-workspace-list [data-workspace-view]').length >= 8",
                timeout=10000,
            )
            page.wait_for_function(
                "() => document.querySelector('#issue-card-section') && !document.querySelector('#issue-card-section').hidden",
                timeout=10000,
            )
            page.wait_for_function(
                "() => document.querySelectorAll('#issue-card-list [data-epic-issue-number]').length > 0",
                timeout=10000,
            )

            issue_card = page.locator(
                '#issue-card-list [data-epic-issue-number="301"]'
            ).first
            assert issue_card.is_visible()
            assert "验证失败" in issue_card.inner_text()
            assert page.locator("#workspace-panel").is_hidden()

            issue_card_action = issue_card.locator(".issue-card__action")
            issue_card_action.click()
            page.wait_for_function(
                '() => document.querySelector(".issue-card__menu") && !document.querySelector(".issue-card__menu").hidden',
                timeout=10000,
            )
            assert page.locator("#detail-drawer").get_attribute("aria-hidden") == "true"
            issue_card_menu_button = issue_card.locator(
                '.issue-card__menu button[data-epic-menu-action="open-detail"]'
            )
            assert issue_card_menu_button.is_visible()

            issue_card_action.press("Escape")
            page.wait_for_function(
                '() => !document.querySelector(".issue-card__menu") || document.querySelector(".issue-card__menu").hidden === true',
                timeout=10000,
            )

            page.click('[data-workspace-view="running_jobs"]')
            page.wait_for_function(
                "() => document.querySelector('#workspace-panel') && !document.querySelector('#workspace-panel').hidden",
                timeout=10000,
            )
            page.wait_for_function(
                "() => document.querySelector('#issue-card-section')?.hidden === true",
                timeout=10000,
            )
            _assert_console_has_no_stray_overlay_or_menu(page)
            assert page.locator(
                '[data-workspace-view="running_jobs"]'
            ).first.is_visible()

            page.click('[data-nav-l1-toggle="overview"]')
            page.wait_for_function(
                "() => document.querySelector('#issue-card-section') && !document.querySelector('#issue-card-section').hidden",
                timeout=10000,
            )
            assert page.locator("#workspace-panel").is_hidden()
            _assert_console_has_no_stray_overlay_or_menu(page)
            issue_card.click()
            page.wait_for_timeout(600)
            epic_detail_title = page.locator("#detail-title").inner_text()
            assert "#301" in epic_detail_title or "Smoke Epic" in epic_detail_title
            assert "verify failed" in page.locator("#detail-meta").inner_text().lower()
            _assert_console_has_no_stray_overlay_or_menu(page)

            assert page.locator("#repo-input").input_value() == repo

            page.click("#locale-zh-btn")
            expect_title = page.locator("h1").inner_text()
            assert expect_title == "仓库控制台"

            sidebar_toggle = page.locator("#sidebar-toggle-btn")
            if sidebar_toggle.get_attribute("aria-expanded") == "false":
                page.click("#sidebar-toggle-btn")
                page.wait_for_timeout(300)
            page.wait_for_timeout(600)
            task_count = page.locator("#sidebar-story-tree [data-work-id]").count()
            assert task_count > 0

            first_task = page.locator("#sidebar-story-tree [data-work-id]").first
            first_task.scroll_into_view_if_needed()
            first_task.click()
            page.wait_for_timeout(600)
            detail_title = page.locator("#detail-title").inner_text()
            assert work_id in detail_title

            page.click('[data-epic-issue-number="301"]')
            page.wait_for_timeout(600)
            page.locator(
                '#detail-tab-overview button[data-story-issue-number="302"]'
            ).first.click()
            page.wait_for_function(
                '() => document.querySelector("#detail-title")?.textContent?.includes("#302") || document.querySelector("#detail-title")?.textContent?.includes("Story")',
                timeout=10000,
            )
            page.wait_for_function(
                '() => document.querySelector("#detail-primary-actions button[data-action-url]")',
                timeout=10000,
            )
            page.locator(
                "#detail-primary-actions button[data-action-url]"
            ).first.click()
            page.wait_for_timeout(300)
            assert (
                page.locator("#confirmation-modal").get_attribute("aria-hidden")
                == "false"
            )
            page.click("#cancel-modal-btn")
            page.wait_for_timeout(300)
            assert (
                page.locator("#confirmation-modal").get_attribute("aria-hidden")
                == "true"
            )
            assert page.locator("#confirmation-modal").is_hidden()

            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


@pytest.mark.integration
def test_console_smoke_lazy_tree_flow():
    repo = f"codefromkarl/stardrifter-smoke-{uuid4().hex[:8]}"
    dsn = os.getenv("TASKPLANE_TEST_POSTGRES_DSN")
    assert dsn is not None
    _seed_smoke_repo(dsn, repo)

    env = os.environ.copy()
    env.update(_required_env(repo))
    log_path = Path("/tmp/stardrifter-ui-smoke-8024.log")
    with log_path.open("w", encoding="utf-8") as handle:
        server = subprocess.Popen(
            [
                "python3",
                "-m",
                "taskplane.hierarchy_api_cli",
                "--host",
                "127.0.0.1",
                "--port",
                str(PORT),
            ],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
    try:
        _wait_for_server(f"{BASE_URL}/console")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{BASE_URL}/console")
            page.evaluate(
                "() => localStorage.setItem('stardrifter-console-sidebar-collapsed', 'true')"
            )
            page.reload()
            page.wait_for_function(
                "() => document.querySelector('#repo-input') && document.querySelector('#summary-title')",
                timeout=10000,
            )
            page.select_option("#repo-input", repo)
            page.click("#load-console-btn")
            page.wait_for_function(
                f"() => document.querySelector('#summary-title')?.textContent?.includes('{repo}')",
                timeout=10000,
            )

            sidebar_toggle = page.locator("#sidebar-toggle-btn")
            assert sidebar_toggle.get_attribute("aria-expanded") == "false"
            assert page.locator("#sidebar-story-tree [data-work-id]").count() == 0

            page.click("#sidebar-toggle-btn")
            page.wait_for_timeout(800)
            assert sidebar_toggle.get_attribute("aria-expanded") == "true"
            assert page.locator("#sidebar-story-tree [data-work-id]").count() > 0

            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


@pytest.mark.integration
def test_console_job_detail_smoke_flow():
    repo = f"codefromkarl/stardrifter-job-{uuid4().hex[:8]}"
    dsn = os.getenv("TASKPLANE_TEST_POSTGRES_DSN")
    assert dsn is not None
    work_id = _seed_smoke_repo(dsn, repo)
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO execution_job (
                    repo, job_kind, status, story_issue_number, work_id, launch_backend,
                    worker_name, pid, command, log_path
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    "story_decomposition",
                    "running",
                    302,
                    work_id,
                    "console",
                    "console-story-302",
                    9302,
                    "story-command",
                    "/tmp/story-302.log",
                ),
            )
        connection.commit()

    env = os.environ.copy()
    env.update(_required_env(repo))
    log_path = Path("/tmp/stardrifter-ui-smoke-8024.log")
    with log_path.open("w", encoding="utf-8") as handle:
        server = subprocess.Popen(
            [
                "python3",
                "-m",
                "taskplane.hierarchy_api_cli",
                "--host",
                "127.0.0.1",
                "--port",
                str(PORT),
            ],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
    try:
        _wait_for_server(f"{BASE_URL}/console")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{BASE_URL}/console")
            page.wait_for_function(
                "() => document.querySelector('#repo-input') && document.querySelector('#summary-title')",
                timeout=10000,
            )
            page.wait_for_timeout(500)
            _assert_console_landing_ready(page)
            page.select_option("#repo-input", repo)
            page.click("#load-console-btn")
            page.wait_for_function(
                f"() => document.querySelector('#summary-title')?.textContent?.includes('{repo}')",
                timeout=10000,
            )
            page.click('[data-workspace-view="running_jobs"]')
            page.wait_for_timeout(800)
            _assert_console_has_no_stray_overlay_or_menu(page)
            page.locator("[data-epic-issue-number]").first.click()
            page.wait_for_timeout(600)
            page.locator("[data-job-id]").first.click()
            page.wait_for_timeout(600)
            detail_title = page.locator("#detail-title").inner_text()
            detail_meta = page.locator("#detail-meta").inner_text()
            assert (
                "#1" in detail_title
                or "Job #" in detail_title
                or "作业 #" in detail_title
            )
            assert "console-story-302" in detail_meta
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


@pytest.mark.integration
def test_console_notifications_and_agents_views_smoke_flow():
    repo = f"codefromkarl/stardrifter-panels-{uuid4().hex[:8]}"
    dsn = os.getenv("TASKPLANE_TEST_POSTGRES_DSN")
    assert dsn is not None
    _seed_smoke_repo(dsn, repo)

    env = os.environ.copy()
    env.update(_required_env(repo))
    log_path = Path("/tmp/stardrifter-ui-smoke-8024.log")
    with log_path.open("w", encoding="utf-8") as handle:
        server = subprocess.Popen(
            [
                "python3",
                "-m",
                "taskplane.hierarchy_api_cli",
                "--host",
                "127.0.0.1",
                "--port",
                str(PORT),
            ],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
    try:
        _wait_for_server(f"{BASE_URL}/console")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{BASE_URL}/console")
            page.wait_for_function(
                "() => document.querySelector('#repo-input') && document.querySelector('#summary-title')",
                timeout=10000,
            )
            page.wait_for_timeout(500)
            _assert_console_landing_ready(page)
            page.select_option("#repo-input", repo)
            page.click("#load-console-btn")
            page.wait_for_function(
                f"() => document.querySelector('#summary-title')?.textContent?.includes('{repo}')",
                timeout=10000,
            )

            page.click('[data-workspace-view="notifications"]')
            page.wait_for_function(
                "() => document.querySelector('#notification-panel') && !document.querySelector('#notification-panel').hidden",
                timeout=10000,
            )
            _assert_console_has_no_stray_overlay_or_menu(page)
            page.wait_for_function(
                "() => document.querySelector('#notification-pending-panel')?.textContent?.length > 0",
                timeout=10000,
            )
            assert (
                "当前没有通知。"
                in page.locator("#notification-pending-panel").inner_text()
            )

            page.click('[data-notification-tab="failed"]')
            page.wait_for_function(
                "() => document.querySelector('#notification-failed-panel')?.textContent?.length > 0",
                timeout=10000,
            )
            assert (
                "当前没有通知。"
                in page.locator("#notification-failed-panel").inner_text()
            )

            page.click('[data-workspace-view="agent_console"]')
            page.wait_for_function(
                "() => document.querySelector('#agent-console-panel') && !document.querySelector('#agent-console-panel').hidden",
                timeout=10000,
            )
            _assert_console_has_no_stray_overlay_or_menu(page)
            page.wait_for_function(
                "() => document.querySelector('#agent-table-body') && document.querySelector('#agent-table-body').textContent?.trim().length > 0",
                timeout=10000,
            )
            agent_body_text = page.locator("#agent-table-body").inner_text()
            assert agent_body_text.strip()

            stats_summary = page.locator("#agent-stats-summary").inner_text()
            assert stats_summary == "" or stats_summary.strip()

            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
