from __future__ import annotations

from uuid import uuid4

from workflows.inspection_graph import build_inspection_graph


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

    assert snapshot.values["report"].case.case_id == "CASE-CHECKPOINT-1"
    assert snapshot.values["severity_assessment"].repair_required is True
