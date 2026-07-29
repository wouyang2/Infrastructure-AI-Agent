from __future__ import annotations

import os
import time
from dataclasses import dataclass
from threading import Lock
from typing import Protocol


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    key: str
    limit: int
    count: int
    remaining: int
    reset_seconds: int


class RateLimiter(Protocol):
    def check(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        ...


class InMemoryRateLimiter:
    def __init__(self):
        self._counters: dict[str, tuple[int, float]] = {}
        self._lock = Lock()

    def check(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        now = time.time()
        window_key = _window_key(key, now=now, window_seconds=window_seconds)
        with self._lock:
            count, expires_at = self._counters.get(
                window_key,
                (0, now + window_seconds),
            )
            if expires_at <= now:
                count = 0
                expires_at = now + window_seconds
            count += 1
            self._counters[window_key] = (count, expires_at)

        return _result(
            key=window_key,
            count=count,
            limit=limit,
            reset_seconds=max(1, int(expires_at - now)),
        )


class RedisRateLimiter:
    def __init__(
        self,
        *,
        redis_url: str = "redis://localhost:6379/0",
        key_prefix: str = "infra_agent:rate_limit",
    ):
        try:
            from redis import Redis
        except ImportError as exc:
            raise RuntimeError(
                "Redis rate limiter requires the 'redis' package. "
                "Install requirements or set RATE_LIMIT_BACKEND=memory."
            ) from exc

        self.client = Redis.from_url(redis_url, decode_responses=True)
        self.key_prefix = key_prefix

    def check(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        now = time.time()
        window_key = f"{self.key_prefix}:{_window_key(key, now=now, window_seconds=window_seconds)}"
        count = int(self.client.incr(window_key))
        if count == 1:
            self.client.expire(window_key, window_seconds)
        ttl = self.client.ttl(window_key)
        reset_seconds = ttl if ttl and ttl > 0 else window_seconds
        return _result(
            key=window_key,
            count=count,
            limit=limit,
            reset_seconds=reset_seconds,
        )


def build_rate_limiter() -> RateLimiter:
    backend = os.getenv("RATE_LIMIT_BACKEND", "memory").lower()
    if backend == "memory":
        return InMemoryRateLimiter()
    if backend == "redis":
        return RedisRateLimiter(redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    raise ValueError(f"Unsupported rate limit backend: {backend}")


def _window_key(key: str, *, now: float, window_seconds: int) -> str:
    window = int(now // window_seconds)
    return f"{key}:{window_seconds}:{window}"


def _result(
    *,
    key: str,
    count: int,
    limit: int,
    reset_seconds: int,
) -> RateLimitResult:
    remaining = max(0, limit - count)
    return RateLimitResult(
        allowed=count <= limit,
        key=key,
        limit=limit,
        count=count,
        remaining=remaining,
        reset_seconds=reset_seconds,
    )
