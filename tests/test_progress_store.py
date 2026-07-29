from __future__ import annotations

import json
import sys
import types

from runtime.progress_store import InMemoryProgressStore, RedisProgressStore


def test_in_memory_progress_store_records_lifecycle() -> None:
    store = InMemoryProgressStore()

    store.start_run("RUN-1")
    store.record_event(
        "RUN-1",
        stage="evidence",
        status="running",
        message="Evidence completed.",
        percent=25,
        metadata={"duration_ms": 12.5},
    )
    progress = store.complete_run("RUN-1")

    assert progress["status"] == "completed"
    assert progress["current_stage"] == "completed"
    assert progress["percent"] == 100
    assert [event["stage"] for event in progress["events"]] == [
        "queued",
        "evidence",
        "completed",
    ]


def test_redis_progress_store_uses_json_snapshots(monkeypatch) -> None:
    fake_client = FakeRedisClient()

    class FakeRedis:
        @staticmethod
        def from_url(redis_url, decode_responses=True):
            assert redis_url == "redis://example.test/0"
            assert decode_responses is True
            return fake_client

    fake_redis_module = types.SimpleNamespace(Redis=FakeRedis)
    monkeypatch.setitem(sys.modules, "redis", fake_redis_module)
    store = RedisProgressStore(redis_url="redis://example.test/0", ttl_seconds=60)

    store.start_run("RUN-2")
    store.record_event(
        "RUN-2",
        stage="severity",
        status="running",
        message="Severity completed.",
        percent=40,
    )
    progress = store.get_progress("RUN-2")

    assert progress is not None
    assert progress["current_stage"] == "severity"
    assert progress["percent"] == 40
    assert fake_client.ttl_by_key["infra_agent:progress:RUN-2"] == 60


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
