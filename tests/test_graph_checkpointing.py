from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from uuid import uuid4

import pytest

from runtime.checkpoints import (
    CHECKPOINT_MSGPACK_ALLOWED_MODULES,
    get_checkpointer,
    get_memory_checkpointer,
)
from workflows.inspection_graph import build_inspection_graph, run_inspection_graph


def test_checkpoint_factory_defaults_to_memory() -> None:
    assert get_checkpointer() is get_memory_checkpointer()


def test_checkpoint_msgpack_allowlist_uses_langgraph_module_name_pairs() -> None:
    assert ("models", "Asset") in CHECKPOINT_MSGPACK_ALLOWED_MODULES
    assert ("models", "InspectionCase") in CHECKPOINT_MSGPACK_ALLOWED_MODULES
    assert all(
        isinstance(item, tuple)
        and len(item) == 2
        and all(isinstance(part, str) for part in item)
        for item in CHECKPOINT_MSGPACK_ALLOWED_MODULES
    )


def test_checkpoint_factory_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match="Unsupported LangGraph checkpoint backend"):
        get_checkpointer(backend="unknown")


def test_checkpoint_factory_explains_missing_sqlite_package(monkeypatch, tmp_path) -> None:
    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.sqlite", None)

    with pytest.raises(RuntimeError, match="langgraph-checkpoint-sqlite"):
        get_checkpointer(
            backend="sqlite",
            sqlite_path=str(tmp_path / "missing-package.sqlite"),
        )


def test_checkpoint_factory_builds_sqlite_checkpointer(monkeypatch, tmp_path) -> None:
    class FakeSqliteSaver:
        @classmethod
        def from_conn_string(cls, conn_string):
            return {"conn_string": conn_string}

    fake_module = types.SimpleNamespace(SqliteSaver=FakeSqliteSaver)
    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.sqlite", fake_module)

    checkpoint_path = tmp_path / "nested" / "checkpoint.sqlite"
    checkpointer = get_checkpointer(
        backend="sqlite",
        sqlite_path=str(checkpoint_path),
    )

    assert checkpointer == {"conn_string": str(checkpoint_path)}
    assert checkpoint_path.parent.exists()


def test_checkpoint_factory_passes_serializer_when_supported(monkeypatch, tmp_path) -> None:
    captured = {}

    class FakeSqliteSaver:
        @classmethod
        def from_conn_string(cls, conn_string, *, serde=None):
            captured["serde"] = serde
            return {"conn_string": conn_string, "serde": serde}

    fake_module = types.SimpleNamespace(SqliteSaver=FakeSqliteSaver)
    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.sqlite", fake_module)

    checkpoint_path = tmp_path / "serde" / "checkpoint.sqlite"
    checkpointer = get_checkpointer(
        backend="sqlite",
        sqlite_path=str(checkpoint_path),
    )

    assert checkpointer["conn_string"] == str(checkpoint_path)
    assert captured["serde"] is not None


def test_checkpoint_factory_enters_sqlite_context_manager(monkeypatch, tmp_path) -> None:
    entered = []

    class FakeContextManager:
        def __init__(self, conn_string):
            self.conn_string = conn_string

        def __enter__(self):
            entered.append(self.conn_string)
            return {"entered_conn_string": self.conn_string}

        def __exit__(self, exc_type, exc, traceback):
            return False

    class FakeSqliteSaver:
        @classmethod
        def from_conn_string(cls, conn_string):
            return FakeContextManager(conn_string)

    fake_module = types.SimpleNamespace(SqliteSaver=FakeSqliteSaver)
    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.sqlite", fake_module)

    checkpoint_path = tmp_path / "context" / "checkpoint.sqlite"
    checkpointer = get_checkpointer(
        backend="sqlite",
        sqlite_path=str(checkpoint_path),
    )

    assert checkpointer == {"entered_conn_string": str(checkpoint_path)}
    assert entered == [str(checkpoint_path)]


def test_inspection_graph_memory_checkpoint_records_thread_state() -> None:
    thread_id = f"checkpoint_{uuid4().hex}"
    graph = build_inspection_graph(
        embedding_backend="fake",
        scheduling_mode="deterministic",
        enable_memory_checkpoint=True,
        enable_workflow_trace=False,
    )

    graph.invoke(
        {
            "input": {
                "asset_id": "CHECKPOINT-1",
                "asset_type": "bridge",
                "asset_name": "Checkpoint Bridge",
                "location": "Checkpoint corridor",
                "criticality": "high",
                "asset_metadata": {},
                "notes": "Inspection found spalling with loose concrete.",
                "image_paths": [],
                "video_paths": [],
                "reason": "routine",
            }
        },
        config={"configurable": {"thread_id": thread_id}},
    )

    snapshot = graph.get_state(config={"configurable": {"thread_id": thread_id}})

    assert snapshot.values["report"]["case"]["case_id"] == "CASE-CHECKPOINT-1"
    assert snapshot.values["severity_assessment"]["repair_required"] is True


def test_inspection_graph_retry_resumes_from_pending_checkpoint() -> None:
    thread_id = f"checkpoint_resume_{uuid4().hex}"
    first_attempt_events = []
    second_attempt_events = []

    def crash_at_severity_start(**event):
        first_attempt_events.append(event)
        if event["stage"] == "severity" and event["message"] == "Severity started.":
            raise RuntimeError("simulated severity crash")

    input_values = {
        "asset_id": "CHECKPOINT-RESUME-1",
        "asset_type": "bridge",
        "asset_name": "Checkpoint Resume Bridge",
        "location": "Checkpoint corridor",
        "criticality": "high",
        "asset_metadata": {},
        "notes": "Inspection found spalling with loose concrete.",
        "image_paths": [],
        "video_paths": [],
        "reason": "routine",
    }

    with pytest.raises(RuntimeError, match="simulated severity crash"):
        run_inspection_graph(
            input_values,
            embedding_backend="fake",
            scheduling_mode="deterministic",
            enable_workflow_trace=False,
            checkpoint_thread_id=thread_id,
            progress_callback=crash_at_severity_start,
        )

    report = run_inspection_graph(
        input_values,
        embedding_backend="fake",
        scheduling_mode="deterministic",
        enable_workflow_trace=False,
        checkpoint_thread_id=thread_id,
        progress_callback=lambda **event: second_attempt_events.append(event),
    )

    second_attempt_stages = [event["stage"] for event in second_attempt_events]

    assert report.case.case_id == "CASE-CHECKPOINT-RESUME-1"
    assert "checkpoint_resume" in second_attempt_stages
    assert "severity" in second_attempt_stages
    assert "intake" not in second_attempt_stages
    assert "video_frame_tool" not in second_attempt_stages
    assert "image_analysis_tool" not in second_attempt_stages
    assert "evidence" not in second_attempt_stages
    assert "severity_guidance_tool" not in second_attempt_stages
    assert [event["stage"] for event in first_attempt_events] == [
        "intake",
        "intake",
        "video_frame_tool",
        "video_frame_tool",
        "image_analysis_tool",
        "image_analysis_tool",
        "evidence",
        "evidence",
        "severity_guidance_tool",
        "severity_guidance_tool",
        "severity",
    ]


def test_sqlite_checkpoint_resumes_after_process_exit(tmp_path) -> None:
    pytest.importorskip("langgraph.checkpoint.sqlite")

    checkpoint_path = tmp_path / "process_exit_checkpoints.sqlite"
    thread_id = f"checkpoint_process_exit_{uuid4().hex}"
    input_values = {
        "asset_id": "CHECKPOINT-PROCESS-EXIT-1",
        "asset_type": "bridge",
        "asset_name": "Checkpoint Process Exit Bridge",
        "location": "Checkpoint corridor",
        "criticality": "high",
        "asset_metadata": {},
        "notes": "Inspection found spalling with loose concrete.",
        "image_paths": [],
        "video_paths": [],
        "reason": "routine",
    }
    input_json = json.dumps(input_values)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")

    crash_code = f"""
import json
import os
from workflows.inspection_graph import run_inspection_graph

input_values = json.loads({input_json!r})

def crash_at_severity_start(**event):
    if event["stage"] == "severity" and event["message"] == "Severity started.":
        os._exit(70)

run_inspection_graph(
    input_values,
    embedding_backend="fake",
    scheduling_mode="deterministic",
    enable_workflow_trace=False,
    checkpoint_backend="sqlite",
    checkpoint_sqlite_path={str(checkpoint_path)!r},
    checkpoint_thread_id={thread_id!r},
    progress_callback=crash_at_severity_start,
)
"""
    resume_code = f"""
import json
from workflows.inspection_graph import run_inspection_graph

events = []
input_values = json.loads({input_json!r})
report = run_inspection_graph(
    input_values,
    embedding_backend="fake",
    scheduling_mode="deterministic",
    enable_workflow_trace=False,
    checkpoint_backend="sqlite",
    checkpoint_sqlite_path={str(checkpoint_path)!r},
    checkpoint_thread_id={thread_id!r},
    progress_callback=lambda **event: events.append(event),
)
print(json.dumps({{"case_id": report.case.case_id, "stages": [event["stage"] for event in events]}}))
"""

    crash_result = subprocess.run(
        [sys.executable, "-c", crash_code],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert crash_result.returncode == 70

    resume_result = subprocess.run(
        [sys.executable, "-c", resume_code],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert resume_result.returncode == 0, resume_result.stderr
    payload = json.loads(resume_result.stdout)

    assert payload["case_id"] == "CASE-CHECKPOINT-PROCESS-EXIT-1"
    assert "checkpoint_resume" in payload["stages"]
    assert "severity" in payload["stages"]
    assert "intake" not in payload["stages"]
    assert "video_frame_tool" not in payload["stages"]
    assert "image_analysis_tool" not in payload["stages"]
    assert "evidence" not in payload["stages"]
