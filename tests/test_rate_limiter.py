"""Unit tests for token bucket rate limiter."""
import time
from app.core.rate_limiter import RateLimiter


def test_rate_limiter_unlimited():
    limiter = RateLimiter(0)
    assert not limiter.is_limited

    t0 = time.monotonic()
    limiter.acquire(1024 * 1024)
    t1 = time.monotonic()
    # Unlimited should return instantly
    assert (t1 - t0) < 0.05


def test_rate_limiter_throttles():
    # Limit to 50 KB/s = 51200 bytes/sec
    rate = 51200
    limiter = RateLimiter(rate)
    assert limiter.is_limited

    # Acquire initial burst
    limiter.acquire(rate)

    t0 = time.monotonic()
    # Acquiring another full second's worth should take ~0.2 - 1.0s
    limiter.acquire(rate // 2)
    t1 = time.monotonic()
    elapsed = t1 - t0
    assert elapsed >= 0.2


def test_rate_limiter_dynamic_change():
    limiter = RateLimiter(1000)
    assert limiter.is_limited
    limiter.set_rate(0)
    assert not limiter.is_limited
