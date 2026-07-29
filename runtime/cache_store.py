from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from threading import Lock
from typing import Any, Protocol


class CacheStore(Protocol):
    def get_json(self, key: str) -> dict[str, Any] | None:
        ...

    def set_json(self, key: str, value: dict[str, Any], *, ttl_seconds: int) -> None:
        ...


class InMemoryCacheStore:
    def __init__(self):
        self._values: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = Lock()

    def get_json(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._values.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at <= time.time():
                self._values.pop(key, None)
                return None
            return deepcopy(value)

    def set_json(self, key: str, value: dict[str, Any], *, ttl_seconds: int) -> None:
        with self._lock:
            self._values[key] = (time.time() + ttl_seconds, deepcopy(value))


class RedisCacheStore:
    def __init__(
        self,
        *,
        redis_url: str = "redis://localhost:6379/0",
        key_prefix: str = "infra_agent:cache",
    ):
        try:
            from redis import Redis
        except ImportError as exc:
            raise RuntimeError(
                "Redis cache store requires the 'redis' package. "
                "Install requirements or set CACHE_STORE_BACKEND=memory."
            ) from exc

        self.client = Redis.from_url(redis_url, decode_responses=True)
        self.key_prefix = key_prefix

    def get_json(self, key: str) -> dict[str, Any] | None:
        raw = self.client.get(self._key(key))
        if raw is None:
            return None
        return json.loads(raw)

    def set_json(self, key: str, value: dict[str, Any], *, ttl_seconds: int) -> None:
        self.client.setex(self._key(key), ttl_seconds, json.dumps(value))

    def _key(self, key: str) -> str:
        return f"{self.key_prefix}:{key}"


def build_cache_store() -> CacheStore:
    backend = os.getenv("CACHE_STORE_BACKEND", "memory").lower()
    if backend == "memory":
        return InMemoryCacheStore()
    if backend == "redis":
        return RedisCacheStore(redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    raise ValueError(f"Unsupported cache store backend: {backend}")
