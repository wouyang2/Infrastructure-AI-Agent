from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

from runtime.inspection_jobs import execute_inspection_run


@dataclass(frozen=True)
class JobDispatchResult:
    backend: str
    job_id: str


class InspectionJobQueue(Protocol):
    def enqueue_inspection(
        self,
        *,
        run_id: str,
        request_data: dict[str, Any],
    ) -> JobDispatchResult:
        ...


class FastAPIBackgroundInspectionJobQueue:
    def __init__(self, background_tasks: Any, *, progress_store: Any | None = None):
        self.background_tasks = background_tasks
        self.progress_store = progress_store

    def enqueue_inspection(
        self,
        *,
        run_id: str,
        request_data: dict[str, Any],
    ) -> JobDispatchResult:
        self.background_tasks.add_task(
            execute_inspection_run,
            run_id,
            request_data,
            self.progress_store,
        )
        return JobDispatchResult(backend="background", job_id=run_id)


class RQInspectionJobQueue:
    def __init__(
        self,
        *,
        redis_url: str = "redis://localhost:6379/0",
        queue_name: str = "inspection-jobs",
        job_timeout_seconds: int = 900,
        retry_max_attempts: int = 3,
        retry_intervals_seconds: list[int] | None = None,
    ):
        try:
            from redis import Redis
            from rq import Queue, Retry
        except ImportError as exc:
            raise RuntimeError(
                "RQ job backend requires the 'rq' and 'redis' packages. "
                "Install requirements or set INSPECTION_JOB_BACKEND=background."
            ) from exc

        self.retry = Retry(
            max=max(0, retry_max_attempts),
            interval=retry_intervals_seconds or [10, 30, 60],
        )
        self.queue = Queue(
            queue_name,
            connection=Redis.from_url(redis_url),
            default_timeout=job_timeout_seconds,
        )

    def enqueue_inspection(
        self,
        *,
        run_id: str,
        request_data: dict[str, Any],
    ) -> JobDispatchResult:
        job = self.queue.enqueue(
            execute_inspection_run,
            run_id,
            request_data,
            job_id=f"inspection-{run_id}",
            retry=self.retry,
        )
        return JobDispatchResult(backend="rq", job_id=job.id)


def build_inspection_job_queue(
    background_tasks: Any | None = None,
    *,
    progress_store: Any | None = None,
) -> InspectionJobQueue:
    backend = os.getenv("INSPECTION_JOB_BACKEND", "background").lower()
    if backend == "background":
        if background_tasks is None:
            raise ValueError("FastAPI background job backend requires background_tasks.")
        return FastAPIBackgroundInspectionJobQueue(
            background_tasks,
            progress_store=progress_store,
        )
    if backend == "rq":
        return RQInspectionJobQueue(
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            queue_name=os.getenv("RQ_INSPECTION_QUEUE", "inspection-jobs"),
            job_timeout_seconds=int(os.getenv("RQ_INSPECTION_JOB_TIMEOUT_SECONDS", "900")),
            retry_max_attempts=int(os.getenv("RQ_INSPECTION_RETRY_MAX_ATTEMPTS", "3")),
            retry_intervals_seconds=_retry_intervals_from_env(
                os.getenv("RQ_INSPECTION_RETRY_INTERVALS_SECONDS", "10,30,60")
            ),
        )
    raise ValueError(f"Unsupported inspection job backend: {backend}")


def _retry_intervals_from_env(value: str) -> list[int]:
    return [
        int(part.strip())
        for part in value.split(",")
        if part.strip()
    ]
