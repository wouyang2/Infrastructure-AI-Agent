from __future__ import annotations

import os
from datetime import datetime
from typing import Any


def fetch_runtime_job_status(
    *,
    job_backend: str | None,
    job_id: str | None,
) -> dict[str, Any] | None:
    if not job_backend or not job_id:
        return None
    if job_backend == "background":
        return {
            "job_backend": "background",
            "job_id": job_id,
            "job_status": "in_process",
            "job_status_message": "Inspection is running in the API process.",
        }
    if job_backend == "rq":
        return _fetch_rq_job_status(job_id)
    return {
        "job_backend": job_backend,
        "job_id": job_id,
        "job_status": "unknown_backend",
        "job_status_message": f"Unknown job backend '{job_backend}'.",
    }


def _fetch_rq_job_status(job_id: str) -> dict[str, Any]:
    try:
        from redis import Redis
        from rq.exceptions import NoSuchJobError
        from rq.job import Job
    except ImportError as exc:
        return {
            "job_backend": "rq",
            "job_id": job_id,
            "job_status": "unavailable",
            "job_status_message": f"RQ status unavailable: {exc}.",
        }

    try:
        job = Job.fetch(
            job_id,
            connection=Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0")),
        )
    except NoSuchJobError:
        return {
            "job_backend": "rq",
            "job_id": job_id,
            "job_status": "missing",
            "job_status_message": "RQ job was not found in Redis.",
        }
    except Exception as exc:
        return {
            "job_backend": "rq",
            "job_id": job_id,
            "job_status": "unavailable",
            "job_status_message": f"RQ status unavailable: {exc}.",
        }

    status = str(job.get_status(refresh=True))
    return {
        "job_backend": "rq",
        "job_id": job_id,
        "job_status": status,
        "job_status_message": _rq_status_message(status),
        "job_enqueued_at": _isoformat(getattr(job, "enqueued_at", None)),
        "job_started_at": _isoformat(getattr(job, "started_at", None)),
        "job_ended_at": _isoformat(getattr(job, "ended_at", None)),
        "job_last_heartbeat": _isoformat(getattr(job, "last_heartbeat", None)),
        "job_worker_name": getattr(job, "worker_name", None),
        "job_retries_left": getattr(job, "retries_left", None),
    }


def _rq_status_message(status: str) -> str:
    messages = {
        "queued": "Inspection job is queued in RQ and waiting for a worker.",
        "scheduled": "Inspection job is scheduled for retry by RQ.",
        "started": "Inspection job is running in an RQ worker.",
        "finished": "Inspection job finished successfully.",
        "failed": "Inspection job failed in RQ.",
        "deferred": "Inspection job is deferred until its dependency is ready.",
        "canceled": "Inspection job was canceled.",
        "stopped": "Inspection job was stopped.",
    }
    return messages.get(status, f"Inspection job status is {status}.")


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
