from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable


class FrozenClock:
    def __init__(self, *, frozen_at: datetime | None = None) -> None:
        self._now = frozen_at or datetime(2026, 1, 1, tzinfo=UTC)
        self._auto_advance_seconds: float = 0

    def now(self) -> datetime:
        current = self._now
        if self._auto_advance_seconds > 0:
            from datetime import timedelta

            self._now = self._now + timedelta(seconds=self._auto_advance_seconds)
        return current

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self._now = self._now + timedelta(seconds=seconds)

    def set_auto_advance(self, seconds: float) -> None:
        self._auto_advance_seconds = seconds

    def to_iso(self) -> str:
        return self.now().isoformat()

    def make_now_fn(self) -> Callable[[], datetime]:
        return self.now


class RealClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def to_iso(self) -> str:
        return self.now().isoformat()

    def make_now_fn(self) -> Callable[[], datetime]:
        return self.now


def default_now_fn() -> str:
    return datetime.now(UTC).isoformat()
