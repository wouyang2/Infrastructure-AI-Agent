from __future__ import annotations

import sys
import types

from runtime.rate_limiter import InMemoryRateLimiter, RedisRateLimiter


def test_in_memory_rate_limiter_blocks_after_limit() -> None:
    limiter = InMemoryRateLimiter()

    first = limiter.check("inspections:test", limit=2, window_seconds=60)
    second = limiter.check("inspections:test", limit=2, window_seconds=60)
    third = limiter.check("inspections:test", limit=2, window_seconds=60)

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.count == 3
    assert third.remaining == 0


def test_redis_rate_limiter_uses_incr_expire_and_ttl(monkeypatch) -> None:
    fake_client = FakeRedisClient()

    class FakeRedis:
        @staticmethod
        def from_url(redis_url, decode_responses=True):
            assert redis_url == "redis://example.test/0"
            assert decode_responses is True
            return fake_client

    monkeypatch.setitem(sys.modules, "redis", types.SimpleNamespace(Redis=FakeRedis))
    limiter = RedisRateLimiter(redis_url="redis://example.test/0", key_prefix="test-rate")

    first = limiter.check("inspections:test", limit=1, window_seconds=30)
    second = limiter.check("inspections:test", limit=1, window_seconds=30)

    assert first.allowed is True
    assert second.allowed is False
    assert second.count == 2
    key = next(iter(fake_client.values))
    assert key.startswith("test-rate:inspections:test:30:")
    assert fake_client.ttl_by_key[key] == 30


class FakeRedisClient:
    def __init__(self):
        self.values = {}
        self.ttl_by_key = {}

    def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key, ttl):
        self.ttl_by_key[key] = ttl

    def ttl(self, key):
        return self.ttl_by_key.get(key, -1)
