"""Sliding-window limiter used for sign-in and sign-up throttling."""

from backend.services.rate_limit import SlidingWindowLimiter


def test_blocks_after_max_events_within_window():
    limiter = SlidingWindowLimiter(max_events=2, window_seconds=60)
    limiter.hit("a", now=0)
    limiter.hit("a", now=1)
    assert not limiter.allowed("a", now=2)
    assert limiter.allowed("b", now=2)


def test_events_expire_after_window():
    limiter = SlidingWindowLimiter(max_events=1, window_seconds=60)
    limiter.hit("a", now=0)
    assert not limiter.allowed("a", now=59)
    assert limiter.allowed("a", now=60)


def test_retry_after_counts_down_to_oldest_event():
    limiter = SlidingWindowLimiter(max_events=1, window_seconds=60)
    limiter.hit("a", now=0)
    assert limiter.retry_after("a", now=50) == 10
    assert limiter.retry_after("b", now=50) == 0


def test_idle_keys_are_forgotten():
    limiter = SlidingWindowLimiter(max_events=3, window_seconds=60)
    for n in range(1000):
        limiter.hit(f"+9190000{n:05d}", now=0)
    assert len(limiter) == 1000
    limiter.allowed("anything", now=61)  # checking an unknown key adds nothing
    for n in range(1000):
        limiter.allowed(f"+9190000{n:05d}", now=61)
    assert len(limiter) == 0


def test_reset_clears_one_key():
    limiter = SlidingWindowLimiter(max_events=1, window_seconds=60)
    limiter.hit("a", now=0)
    limiter.reset("a")
    assert limiter.allowed("a", now=1)


def test_keys_tried_once_are_swept():
    from backend.services import rate_limit

    limiter = SlidingWindowLimiter(max_events=3, window_seconds=60)
    for n in range(rate_limit.SWEEP_EVERY - 1):
        limiter.hit(f"spray-{n}", now=0)
    limiter.hit("latest", now=61)  # triggers the periodic sweep
    assert len(limiter) == 1
