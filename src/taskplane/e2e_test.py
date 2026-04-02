#!/usr/bin/env python
"""
End-to-End Test Suite for Taskplane Web UI

Tests the multi-project API endpoints and console functionality.

Usage:
    python -m taskplane.e2e_test \
        --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import sys
import json
from typing import Any
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError


class E2ETester:
    """End-to-end tester for Web UI API endpoints."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.results: list[dict[str, Any]] = []

    def _get(self, endpoint: str, expect_json: bool = True) -> tuple[bool, Any, str]:
        """Send GET request and return (success, data, error_message)."""
        url = f"{self.base_url}{endpoint}"
        try:
            with urlopen(url, timeout=10) as response:
                raw_data = response.read().decode("utf-8")
                if expect_json:
                    data = json.loads(raw_data)
                else:
                    data = raw_data
                return True, data, ""
        except HTTPError as e:
            return False, None, f"HTTP {e.code}: {e.reason}"
        except URLError as e:
            return False, None, f"URL Error: {e.reason}"
        except json.JSONDecodeError as e:
            return False, None, f"JSON decode error: {e}"
        except Exception as e:
            return False, None, f"Unexpected error: {e}"

    def _assert(self, condition: bool, message: str, details: str = "") -> bool:
        """Assert a condition and record the result."""
        passed = condition
        self.results.append({"passed": passed, "message": message, "details": details})
        return passed

    def test_api_repos(self) -> bool:
        """Test /api/repos endpoint."""
        success, data, error = self._get("/api/repos")
        if not success:
            return self._assert(False, "/api/repos - Request failed", error)

        if "repositories" not in data:
            return self._assert(False, "/api/repos - Missing 'repositories' key")

        repos = data["repositories"]
        if not isinstance(repos, list):
            return self._assert(False, "/api/repos - 'repositories' should be a list")

        return self._assert(
            len(repos) > 0,
            f"/api/repos - Found {len(repos)} repositories",
            f"First repo: {repos[0].get('repo', 'N/A') if repos else 'N/A'}",
        )

    def test_api_portfolio(self) -> bool:
        """Test /api/portfolio endpoint - multi-project summary."""
        success, data, error = self._get("/api/portfolio")
        if not success:
            return self._assert(False, "/api/portfolio - Request failed", error)

        if "repos" not in data:
            return self._assert(False, "/api/portfolio - Missing 'repos' key")

        repos = data["repos"]
        if not isinstance(repos, list):
            return self._assert(False, "/api/portfolio - 'repos' should be a list")

        # Check required fields in first repo
        if repos:
            required_fields = [
                "repo",
                "active_agent_count",
                "running_task_count",
                "operator_attention_required",
                "epic_count",
                "story_count",
                "task_count",
                "ready_task_count",
                "blocked_task_count",
            ]
            first_repo = repos[0]
            missing_fields = [f for f in required_fields if f not in first_repo]
            if missing_fields:
                return self._assert(
                    False,
                    "/api/portfolio - Missing required fields",
                    f"Missing: {missing_fields}",
                )

        return self._assert(
            True, f"/api/portfolio - Found {len(repos)} repos with valid schema"
        )

    def test_api_ai_decisions(self) -> bool:
        """Test /api/ai-decisions endpoint."""
        success, data, error = self._get("/api/ai-decisions")
        if not success:
            return self._assert(False, "/api/ai-decisions - Request failed", error)

        if "decisions" not in data:
            return self._assert(False, "/api/ai-decisions - Missing 'decisions' key")

        decisions = data["decisions"]
        if not isinstance(decisions, list):
            return self._assert(
                False, "/api/ai-decisions - 'decisions' should be a list"
            )

        return self._assert(
            True, f"/api/ai-decisions - Returns valid list ({len(decisions)} items)"
        )

    def test_api_notifications(self) -> bool:
        """Test /api/notifications endpoint."""
        success, data, error = self._get("/api/notifications")
        if not success:
            return self._assert(False, "/api/notifications - Request failed", error)

        if "notifications" not in data:
            return self._assert(
                False, "/api/notifications - Missing 'notifications' key"
            )

        notifications = data["notifications"]
        if not isinstance(notifications, list):
            return self._assert(
                False, "/api/notifications - 'notifications' should be a list"
            )

        # Note: pending_count field may or may not be present depending on API implementation
        # The important thing is that the endpoint returns valid data
        pending_count = data.get("pending_count", len(notifications))

        return self._assert(
            True, f"/api/notifications - Returns valid data (pending: {pending_count})"
        )

    def test_api_agents(self) -> bool:
        """Test /api/agents endpoint."""
        success, data, error = self._get("/api/agents")
        if not success:
            return self._assert(False, "/api/agents - Request failed", error)

        if "agents" not in data:
            return self._assert(False, "/api/agents - Missing 'agents' key")

        agents = data["agents"]
        if not isinstance(agents, list):
            return self._assert(False, "/api/agents - 'agents' should be a list")

        # Check required fields in first agent
        if agents:
            required_fields = ["agent_name", "agent_type", "status", "health_status"]
            first_agent = agents[0]
            missing_fields = [f for f in required_fields if f not in first_agent]
            if missing_fields:
                return self._assert(
                    False,
                    "/api/agents - Missing required fields",
                    f"Missing: {missing_fields}",
                )

        return self._assert(
            True, f"/api/agents - Found {len(agents)} agents with valid schema"
        )

    def test_console_page(self) -> bool:
        """Test /console HTML page loads."""
        success, data, error = self._get("/console", expect_json=False)
        if not success:
            return self._assert(False, "/console - Request failed", error)

        if not isinstance(data, str):
            return self._assert(False, "/console - Expected HTML string")

        # Check for expected HTML elements
        checks = [
            ("<html", "HTML doctype"),
            ('id="root"', "React root element"),
            ("console.bundle.js", "React bundle script"),
            ("console.css", "Console stylesheet"),
            ("Stardrifter Console", "Page title"),
        ]

        failed_checks = []
        for check_str, description in checks:
            if check_str not in data:
                failed_checks.append(description)

        if failed_checks:
            return self._assert(
                False,
                "/console - Missing expected elements",
                f"Missing: {failed_checks}",
            )

        return self._assert(
            True, "/console - HTML page loads with all expected elements"
        )

    def test_console_bundle_js(self) -> bool:
        """Test /console.bundle.js loads."""
        success, data, error = self._get("/console.bundle.js", expect_json=False)
        if not success:
            return self._assert(False, "/console.bundle.js - Request failed", error)

        if not isinstance(data, str):
            return self._assert(
                False, "/console.bundle.js - Expected JavaScript string"
            )

        # Check for expected JavaScript patterns
        checks = [
            ("createRoot", "React root bootstrap"),
            ("detail-drawer", "Console detail drawer hook"),
            ("issue-card-section", "Overview compatibility hook"),
        ]

        failed_checks = []
        for check_str, description in checks:
            if check_str not in data:
                failed_checks.append(description)

        if failed_checks:
            return self._assert(
                False,
                "/console.bundle.js - Missing expected code",
                f"Missing: {failed_checks}",
            )

        return self._assert(
            True, "/console.bundle.js - JavaScript loads with expected bundle markers"
        )

    def run_all_tests(self) -> bool:
        """Run all E2E tests and return overall success."""
        print("=" * 60)
        print("Taskplane Web UI - End-to-End Tests")
        print("=" * 60)
        print(f"Base URL: {self.base_url}")
        print()

        tests = [
            ("API: Repositories", self.test_api_repos),
            ("API: Portfolio Summary", self.test_api_portfolio),
            ("API: AI Decisions", self.test_api_ai_decisions),
            ("API: Notifications", self.test_api_notifications),
            ("API: Agents Status", self.test_api_agents),
            ("UI: Console Page", self.test_console_page),
            ("UI: Console Bundle JavaScript", self.test_console_bundle_js),
        ]

        for name, test_func in tests:
            print(f"Running: {name}...", end=" ")
            try:
                result = test_func()
                status = "✅ PASS" if result else "❌ FAIL"
                print(status)
            except Exception as e:
                print(f"❌ ERROR: {e}")
                self.results.append(
                    {"passed": False, "message": name, "details": str(e)}
                )

        print()
        print("=" * 60)

        passed = sum(1 for r in self.results if r["passed"])
        total = len(self.results)
        print(f"Results: {passed}/{total} tests passed")

        if passed == total:
            print("🎉 All tests passed!")
            return True
        else:
            print("\nFailed tests:")
            for r in self.results:
                if not r["passed"]:
                    print(f"  - {r['message']}: {r['details']}")
            return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="End-to-end tests for Stardrifter Web UI"
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://localhost:8000",
        help="Base URL of the Web UI server (default: http://localhost:8000)",
    )

    args = parser.parse_args()

    tester = E2ETester(args.base_url)
    success = tester.run_all_tests()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
