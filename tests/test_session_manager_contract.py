from __future__ import annotations

from taskplane.session_manager import InMemorySessionManager
from session_manager_contract import run_session_manager_contract_tests


class TestInMemorySessionManagerContract:
    def test_contract(self) -> None:
        mgr = InMemorySessionManager()
        run_session_manager_contract_tests(mgr)


class TestContractMultipleRuns:
    def test_fresh_instance_per_test(self) -> None:
        for _ in range(3):
            mgr = InMemorySessionManager()
            run_session_manager_contract_tests(mgr)
