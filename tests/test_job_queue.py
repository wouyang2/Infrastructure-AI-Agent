from __future__ import annotations

import sys
import types

import pytest

from runtime.inspection_jobs import execute_inspection_run, _current_rq_retry_metadata
from runtime.inspection_jobs import _progress_callback_for_run
from runtime.crash_settings import load_crash_simulation_settings
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
    assert result.job_id == "inspection-RUN-2"
    retry = fake_queue.enqueued[0][3]
    assert retry.max == 4
    assert retry.interval == [5, 15, 45]
    assert fake_queue.enqueued == [
        (
            execute_inspection_run,
            ("RUN-2", {"asset_id": "A-2"}),
            "inspection-RUN-2",
            retry,
        ),
    ]


def test_current_rq_retry_metadata_reports_attempt(monkeypatch) -> None:
    monkeypatch.setenv("RQ_INSPECTION_RETRY_MAX_ATTEMPTS", "3")
    fake_job = types.SimpleNamespace(
        id="inspection-RUN-3",
        retry=types.SimpleNamespace(max=0),
        retries_left=2,
    )

    monkeypatch.setitem(
        sys.modules,
        "rq",
        types.SimpleNamespace(get_current_job=lambda: fake_job),
    )

    assert _current_rq_retry_metadata() == {
        "job_id": "inspection-RUN-3",
        "attempt": 2,
        "max_attempts": 4,
        "retries_left": 2,
    }


def test_current_rq_retry_metadata_is_absent_outside_rq(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "rq",
        types.SimpleNamespace(get_current_job=lambda: None),
    )

    assert _current_rq_retry_metadata() is None


def test_execute_inspection_run_loads_dotenv_before_progress_store(monkeypatch) -> None:
    calls = []

    def fake_load_dotenv():
        calls.append("loaded")

    monkeypatch.setattr("runtime.inspection_jobs.load_dotenv_if_available", fake_load_dotenv)
    monkeypatch.setattr("runtime.inspection_jobs.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        "runtime.inspection_jobs.mark_inspection_running",
        lambda session, run_id: types.SimpleNamespace(status="completed", report_json={}),
    )

    execute_inspection_run("RUN-DOTENV-1", {"asset_id": "A-1"})

    assert calls == ["loaded"]


def test_progress_callback_can_simulate_one_retryable_crash(monkeypatch, tmp_path) -> None:
    store = FakeProgressStore()
    monkeypatch.delenv("INSPECTION_CRASH_MODE", raising=False)
    monkeypatch.setenv("INSPECTION_SIMULATE_CRASH_AFTER_STAGE", "severity")
    monkeypatch.setenv("INSPECTION_CRASH_MARKER_DIR", str(tmp_path))
    callback = _progress_callback_for_run("RUN-CRASH-1", store)

    event = {
        "stage": "severity",
        "status": "running",
        "message": "Severity completed.",
        "percent": 40,
    }

    try:
        callback(**event)
    except RuntimeError as exc:
        assert "Simulated retryable inspection crash" in str(exc)
    else:
        raise AssertionError("Expected first matching event to raise a simulated crash.")

    callback(**event)

    assert len(store.events) == 2


def test_progress_callback_can_simulate_retryable_crash_from_settings_file(
    monkeypatch,
    tmp_path,
) -> None:
    store = FakeProgressStore()
    monkeypatch.delenv("INSPECTION_CRASH_MODE", raising=False)
    settings_path = tmp_path / "inspection_crash_settings.json"
    settings_path.write_text(
        """
        {
          "mode": "retryable",
          "stage": "planning",
          "status": "running",
          "marker_dir": "%s"
        }
        """
        % str(tmp_path),
        encoding="utf-8",
    )
    monkeypatch.setenv("INSPECTION_CRASH_SETTINGS_FILE", str(settings_path))
    callback = _progress_callback_for_run("RUN-FILE-CRASH-1", store)

    event = {
        "stage": "planning",
        "status": "running",
        "message": "Planning started.",
        "percent": 60,
    }

    with pytest.raises(RuntimeError) as exc_info:
        callback(**event)

    assert "Simulated retryable inspection crash" in str(exc_info.value)
    assert (tmp_path / "RUN-FILE-CRASH-1_planning.marker").exists()


def test_crash_settings_env_overrides_settings_file(monkeypatch, tmp_path) -> None:
    settings_path = tmp_path / "inspection_crash_settings.json"
    settings_path.write_text(
        """
        {
          "mode": "retryable",
          "stage": "planning",
          "status": "running",
          "marker_dir": "from-file"
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("INSPECTION_CRASH_SETTINGS_FILE", str(settings_path))
    monkeypatch.setenv("INSPECTION_CRASH_MODE", "hard")
    monkeypatch.setenv("INSPECTION_CRASH_STAGE", "scheduling")
    monkeypatch.setenv("INSPECTION_CRASH_MARKER_DIR", str(tmp_path))

    settings = load_crash_simulation_settings()

    assert settings.mode == "hard"
    assert settings.stage == "scheduling"
    assert settings.marker_dir == str(tmp_path)


def test_crash_settings_loads_default_local_file(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("INSPECTION_CRASH_MODE", raising=False)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "inspection_crash_settings.json").write_text(
        """
        {
          "mode": "hard",
          "stage": "report",
          "status": "running",
          "marker_dir": "custom-markers",
          "hard_exit_code": 77
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = load_crash_simulation_settings()

    assert settings.mode == "hard"
    assert settings.stage == "report"
    assert settings.marker_dir == "custom-markers"
    assert settings.hard_exit_code == 77


def test_progress_callback_ignores_non_matching_crash_stage(monkeypatch, tmp_path) -> None:
    store = FakeProgressStore()
    monkeypatch.setenv("INSPECTION_SIMULATE_CRASH_AFTER_STAGE", "severity")
    monkeypatch.setenv("INSPECTION_CRASH_MARKER_DIR", str(tmp_path))
    callback = _progress_callback_for_run("RUN-CRASH-2", store)

    callback(
        stage="evidence",
        status="running",
        message="Evidence completed.",
        percent=25,
    )

    assert len(store.events) == 1


def test_progress_callback_can_simulate_one_hard_crash(monkeypatch, tmp_path) -> None:
    store = FakeProgressStore()
    monkeypatch.delenv("INSPECTION_CRASH_MODE", raising=False)
    monkeypatch.setenv("INSPECTION_SIMULATE_HARD_CRASH_AFTER_STAGE", "severity")
    monkeypatch.setenv("INSPECTION_CRASH_MARKER_DIR", str(tmp_path))
    monkeypatch.setenv("INSPECTION_HARD_CRASH_EXIT_CODE", "70")
    monkeypatch.setattr("runtime.inspection_jobs._HARD_EXIT", fake_hard_exit)
    callback = _progress_callback_for_run("RUN-HARD-CRASH-1", store)

    event = {
        "stage": "severity",
        "status": "running",
        "message": "Severity completed.",
        "percent": 40,
    }

    with pytest.raises(FakeHardExit) as exc_info:
        callback(**event)

    assert exc_info.value.exit_code == 70
    assert len(store.events) == 1
    assert (tmp_path / "RUN-HARD-CRASH-1_severity_hard.marker").exists()

    callback(**event)

    assert len(store.events) == 2


def test_progress_callback_ignores_non_matching_hard_crash_stage(monkeypatch, tmp_path) -> None:
    store = FakeProgressStore()
    monkeypatch.setenv("INSPECTION_SIMULATE_HARD_CRASH_AFTER_STAGE", "severity")
    monkeypatch.setenv("INSPECTION_CRASH_MARKER_DIR", str(tmp_path))
    monkeypatch.setattr("runtime.inspection_jobs._HARD_EXIT", fake_hard_exit)
    callback = _progress_callback_for_run("RUN-HARD-CRASH-2", store)

    callback(
        stage="evidence",
        status="running",
        message="Evidence completed.",
        percent=25,
    )

    assert len(store.events) == 1


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


class FakeProgressStore:
    def __init__(self):
        self.events = []

    def record_event(self, run_id, **event):
        self.events.append((run_id, event))


class FakeSession:
    def close(self):
        pass


class FakeHardExit(Exception):
    def __init__(self, exit_code: int):
        super().__init__(f"hard exit {exit_code}")
        self.exit_code = exit_code


def fake_hard_exit(exit_code: int) -> None:
    raise FakeHardExit(exit_code)
