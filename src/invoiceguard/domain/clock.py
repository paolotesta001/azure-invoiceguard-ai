"""Injectable clock and id factory, so time-dependent logic is testable."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """Current time, timezone-aware (UTC)."""
    return datetime.now(UTC)


def new_id() -> str:
    """Random identifier for entities."""
    return uuid.uuid4().hex
