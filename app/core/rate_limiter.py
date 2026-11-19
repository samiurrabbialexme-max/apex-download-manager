"""Token-bucket rate limiter for thread-safe bandwidth throttling."""
import threading
import time


class RateLimiter:
    """Thread-safe Token Bucket rate limiter for bandwidth throttling."""

    def __init__(self, max_bytes_per_sec: int = 0):
        self._rate = float(max_bytes_per_sec)  # 0 = unlimited
        self._capacity = max(float(max_bytes_per_sec), 64 * 1024.0) if max_bytes_per_sec > 0 else 0.0
        self._tokens = self._capacity
        self._last_time = time.monotonic()
        self._lock = threading.Lock()

    def set_rate(self, max_bytes_per_sec: int) -> None:
        """Updates the speed limit dynamically during an ongoing download."""
        with self._lock:
            self._rate = float(max_bytes_per_sec)
            self._capacity = max(float(max_bytes_per_sec), 64 * 1024.0) if max_bytes_per_sec > 0 else 0.0
            self._tokens = min(self._tokens, self._capacity)
            self._last_time = time.monotonic()

    @property
    def is_limited(self) -> bool:
        return self._rate > 0

    def acquire(self, num_bytes: int) -> None:
        """Throttles execution if necessary to obey the target byte rate."""
        if self._rate <= 0 or num_bytes <= 0:
            return

        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_time
                self._last_time = now

                # Replenish tokens based on elapsed seconds
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)

                if self._tokens >= num_bytes:
                    self._tokens -= num_bytes
                    return

                # Calculate required sleep time
                deficit = num_bytes - self._tokens
                sleep_sec = deficit / self._rate

            # Sleep outside of lock to allow other threads to progress
            time.sleep(min(sleep_sec, 0.5))
