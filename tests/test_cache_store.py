from __future__ import annotations

import json
import sys
import time
import types

from runtime.cache_store import InMemoryCacheStore, RedisCacheStore


def test_in_memory_cache_store_expires_json_values() -> None:
    cache = InMemoryCacheStore()

    cache.set_json("weather:1", {"condition": "Clear"}, ttl_seconds=1)

    assert cache.get_json("weather:1") == {"condition": "Clear"}
    time.sleep(1.01)
    assert cache.get_json("weather:1") is None


def test_redis_cache_store_uses_prefixed_json_keys(monkeypatch) -> None:
    fake_client = FakeRedisClient()

    class FakeRedis:
        @staticmethod
        def from_url(redis_url, decode_responses=True):
            assert redis_url == "redis://example.test/0"
            assert decode_responses is True
            return fake_client

    monkeypatch.setitem(sys.modules, "redis", types.SimpleNamespace(Redis=FakeRedis))
    cache = RedisCacheStore(redis_url="redis://example.test/0", key_prefix="test-cache")

    cache.set_json("provider:abc", {"ok": True}, ttl_seconds=30)

    assert cache.get_json("provider:abc") == {"ok": True}
    assert fake_client.ttl_by_key["test-cache:provider:abc"] == 30


class FakeRedisClient:
    def __init__(self):
        self.values = {}
        self.ttl_by_key = {}

    def setex(self, key, ttl, value):
        json.loads(value)
        self.values[key] = value
        self.ttl_by_key[key] = ttl

    def get(self, key):
        return self.values.get(key)
