from __future__ import annotations

import sys
import types

from runtime.inspection_jobs import execute_inspection_run
from runtime.job_queue import (
    FastAPIBackgroundInspectionJobQueue,
    RQInspectionJobQueue,
)


def test_fastapi_background_job_queue_adds_inspection_task() -> None:
    background_tasks = FakeBackgroundTasks()
    progress_store = object()
    queue = FastAPIBackgroundInspectionJobQueue(
        background_tasks,
        progress_store=progress_store,
    )

    result = queue.enqueue_inspection(
        run_id="RUN-1",
        request_data={"asset_id": "A-1"},
    )

    assert result.backend == "background"
    assert result.job_id == "RUN-1"
    assert background_tasks.tasks == [
        (execute_inspection_run, ("RUN-1", {"asset_id": "A-1"}, progress_store)),
    ]


def test_rq_job_queue_enqueues_importable_inspection_job(monkeypatch) -> None:
    fake_queue = FakeRQQueue()

    class FakeRedis:
        @staticmethod
        def from_url(redis_url):
            assert redis_url == "redis://example.test/0"
            return "redis-connection"

    class FakeQueue:
        def __new__(cls, *args, **kwargs):
            fake_queue.init_args = args
            fake_queue.init_kwargs = kwargs
            return fake_queue

    class FakeRetry:
        def __init__(self, *, max, interval):
            self.max = max
            self.interval = interval

    monkeypatch.setitem(sys.modules, "redis", types.SimpleNamespace(Redis=FakeRedis))
    monkeypatch.setitem(
        sys.modules,
        "rq",
        types.SimpleNamespace(Queue=FakeQueue, Retry=FakeRetry),
    )

    queue = RQInspectionJobQueue(
        redis_url="redis://example.test/0",
        queue_name="inspection-test",
        job_timeout_seconds=120,
        retry_max_attempts=4,
        retry_intervals_seconds=[5, 15, 45],
    )
    result = queue.enqueue_inspection(
        run_id="RUN-2",
        request_data={"asset_id": "A-2"},
    )

    assert fake_queue.init_args == ("inspection-test",)
    assert fake_queue.init_kwargs == {
        "connection": "redis-connection",
        "default_timeout": 120,
    }
    assert result.backend == "rq"
    assert result.job_id == "inspection:RUN-2"
    retry = fake_queue.enqueued[0][3]
    assert retry.max == 4
    assert retry.interval == [5, 15, 45]
    assert fake_queue.enqueued == [
        (
            execute_inspection_run,
            ("RUN-2", {"asset_id": "A-2"}),
            "inspection:RUN-2",
            retry,
        ),
    ]


class FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *args):
        self.tasks.append((fn, args))


class FakeRQQueue:
    def __init__(self):
        self.init_args = None
        self.init_kwargs = None
        self.enqueued = []

    def enqueue(self, fn, *args, job_id=None, retry=None):
        self.enqueued.append((fn, args, job_id, retry))
        return types.SimpleNamespace(id=job_id)
