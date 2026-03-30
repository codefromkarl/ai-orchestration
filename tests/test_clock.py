from __future__ import annotations

from datetime import UTC, datetime, timedelta

from stardrifter_orchestration_mvp.clock import FrozenClock, RealClock


class TestFrozenClock:
    def test_default_time(self) -> None:
        clock = FrozenClock()
        assert clock.now() == datetime(2026, 1, 1, tzinfo=UTC)

    def test_custom_time(self) -> None:
        t = datetime(2025, 6, 15, 12, 0, tzinfo=UTC)
        clock = FrozenClock(frozen_at=t)
        assert clock.now() == t

    def test_advance(self) -> None:
        clock = FrozenClock()
        clock.advance(3600)
        assert clock.now() == datetime(2026, 1, 1, 1, 0, tzinfo=UTC)

    def test_auto_advance(self) -> None:
        clock = FrozenClock()
        clock.set_auto_advance(60)
        t1 = clock.now()
        t2 = clock.now()
        assert t2 - t1 == timedelta(seconds=60)

    def test_to_iso(self) -> None:
        clock = FrozenClock()
        iso = clock.to_iso()
        assert "2026-01-01" in iso


class TestRealClock:
    def test_now_returns_datetime(self) -> None:
        clock = RealClock()
        assert isinstance(clock.now(), datetime)

    def test_to_iso_returns_string(self) -> None:
        clock = RealClock()
        iso = clock.to_iso()
        assert isinstance(iso, str)
        assert "T" in iso


class TestClockWithWakeup:
    def test_far_future_not_wakeable(self) -> None:
        from stardrifter_orchestration_mvp.session_manager import InMemorySessionManager

        far_future = datetime(2099, 1, 1, tzinfo=UTC).isoformat()
        mgr = InMemorySessionManager()
        session = mgr.create_session(work_id="w1")
        mgr.suspend_session(session.id, waiting_reason="timer", wake_after=far_future)
        wakeable = mgr.list_wakeable_sessions()
        assert len(wakeable) == 0

    def test_past_time_is_wakeable(self) -> None:
        from stardrifter_orchestration_mvp.session_manager import InMemorySessionManager

        past = datetime(2000, 1, 1, tzinfo=UTC).isoformat()
        mgr = InMemorySessionManager()
        session = mgr.create_session(work_id="w1")
        mgr.suspend_session(session.id, waiting_reason="timer", wake_after=past)
        wakeable = mgr.list_wakeable_sessions()
        assert len(wakeable) == 1
        assert wakeable[0].id == session.id

    def test_frozen_clock_advances_time(self) -> None:
        clock = FrozenClock(frozen_at=datetime(2026, 1, 1, tzinfo=UTC))
        t1 = clock.now()
        clock.advance(3600)
        t2 = clock.now()
        assert (t2 - t1).total_seconds() == 3600
