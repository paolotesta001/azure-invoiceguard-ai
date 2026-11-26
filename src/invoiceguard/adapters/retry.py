"""Retry with exponential backoff + jitter, honouring ``retry-after`` hints."""

import random
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class TransientError(Exception):
    """A failure worth retrying (timeouts, HTTP 429/5xx)."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def call_with_retry(
    func: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
) -> T:
    """Call ``func``; retry on ``TransientError`` up to ``attempts`` times in total."""
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    jitter = rng or random.Random()  # noqa: S311 - jitter, not cryptography
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except TransientError as exc:
            if attempt == attempts:
                raise
            backoff = min(max_delay, base_delay * 2 ** (attempt - 1))
            delay = max(backoff * (0.5 + jitter.random() / 2), exc.retry_after or 0.0)
            sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover
