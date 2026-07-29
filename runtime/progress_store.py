from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Protocol


ProgressStatus = str


class ProgressStore(Protocol):
    def start_run(self, run_id: str) -> dict[str, Any]:
        ...

    def record_event(
        self,
        run_id: str,
        *,
        stage: str,
        status: ProgressStatus,
        message: str,
        percent: int,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...

    def complete_run(self, run_id: str, *, message: str = "Inspection completed.") -> dict[str, Any]:
        ...

    def fail_run(self, run_id: str, *, message: str) -> dict[str, Any]:
        ...

    def get_progress(self, run_id: str) -> dict[str, Any] | None:
        ...


class InMemoryProgressStore:
    def __init__(self):
        self._runs: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def start_run(self, run_id: str) -> dict[str, Any]:
        snapshot = _new_snapshot(run_id)
        with self._lock:
            self._runs[run_id] = snapshot
        return deepcopy(snapshot)

    def record_event(
        self,
        run_id: str,
        *,
        stage: str,
        status: ProgressStatus,
        message: str,
        percent: int,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            snapshot = self._runs.setdefault(run_id, _new_snapshot(run_id))
            _append_event(
                snapshot,
                stage=stage,
                status=status,
                message=message,
                percent=percent,
                metadata=metadata,
            )
            return deepcopy(snapshot)

    def complete_run(self, run_id: str, *, message: str = "Inspection completed.") -> dict[str, Any]:
        return self.record_event(
            run_id,
            stage="completed",
            status="completed",
            message=message,
            percent=100,
        )

    def fail_run(self, run_id: str, *, message: str) -> dict[str, Any]:
        return self.record_event(
            run_id,
            stage="failed",
            status="failed",
            message=message,
            percent=100,
        )

    def get_progress(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            snapshot = self._runs.get(run_id)
            return deepcopy(snapshot) if snapshot else None


class RedisProgressStore:
    def __init__(
        self,
        *,
        redis_url: str = "redis://localhost:6379/0",
        key_prefix: str = "infra_agent:progress",
        ttl_seconds: int = 86400,
    ):
        try:
            from redis import Redis
        except ImportError as exc:
            raise RuntimeError(
                "Redis progress store requires the 'redis' package. "
                "Install requirements or set PROGRESS_STORE_BACKEND=memory."
            ) from exc

        self.client = Redis.from_url(redis_url, decode_responses=True)
        self.key_prefix = key_prefix
        self.ttl_seconds = ttl_seconds

    def start_run(self, run_id: str) -> dict[str, Any]:
        snapshot = _new_snapshot(run_id)
        self._save(run_id, snapshot)
        return snapshot

    def record_event(
        self,
        run_id: str,
        *,
        stage: str,
        status: ProgressStatus,
        message: str,
        percent: int,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        snapshot = self.get_progress(run_id) or _new_snapshot(run_id)
        _append_event(
            snapshot,
            stage=stage,
            status=status,
            message=message,
            percent=percent,
            metadata=metadata,
        )
        self._save(run_id, snapshot)
        return snapshot

    def complete_run(self, run_id: str, *, message: str = "Inspection completed.") -> dict[str, Any]:
        return self.record_event(
            run_id,
            stage="completed",
            status="completed",
            message=message,
            percent=100,
        )

    def fail_run(self, run_id: str, *, message: str) -> dict[str, Any]:
        return self.record_event(
            run_id,
            stage="failed",
            status="failed",
            message=message,
            percent=100,
        )

    def get_progress(self, run_id: str) -> dict[str, Any] | None:
        raw = self.client.get(self._key(run_id))
        if raw is None:
            return None
        return json.loads(raw)

    def _save(self, run_id: str, snapshot: dict[str, Any]) -> None:
        self.client.setex(self._key(run_id), self.ttl_seconds, json.dumps(snapshot))

    def _key(self, run_id: str) -> str:
        return f"{self.key_prefix}:{run_id}"


def build_progress_store() -> ProgressStore:
    backend = os.getenv("PROGRESS_STORE_BACKEND", "memory").lower()
    if backend == "memory":
        return InMemoryProgressStore()
    if backend == "redis":
        return RedisProgressStore(
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            ttl_seconds=int(os.getenv("PROGRESS_STORE_TTL_SECONDS", "86400")),
        )
    raise ValueError(f"Unsupported progress store backend: {backend}")


def _new_snapshot(run_id: str) -> dict[str, Any]:
    now = _utc_now()
    return {
        "run_id": run_id,
        "status": "running",
        "current_stage": "queued",
        "message": "Inspection run queued.",
        "percent": 0,
        "started_at": now,
        "updated_at": now,
        "events": [
            {
                "stage": "queued",
                "status": "running",
                "message": "Inspection run queued.",
                "percent": 0,
                "timestamp": now,
                "metadata": {},
            }
        ],
    }


def _append_event(
    snapshot: dict[str, Any],
    *,
    stage: str,
    status: ProgressStatus,
    message: str,
    percent: int,
    metadata: dict[str, Any] | None = None,
) -> None:
    timestamp = _utc_now()
    bounded_percent = max(0, min(100, int(percent)))
    snapshot["status"] = status
    snapshot["current_stage"] = stage
    snapshot["message"] = message
    snapshot["percent"] = bounded_percent
    snapshot["updated_at"] = timestamp
    snapshot.setdefault("events", []).append(
        {
            "stage": stage,
            "status": status,
            "message": message,
            "percent": bounded_percent,
            "timestamp": timestamp,
            "metadata": metadata or {},
        }
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
