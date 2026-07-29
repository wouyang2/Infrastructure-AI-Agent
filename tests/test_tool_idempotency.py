from __future__ import annotations

from uuid import uuid4

import pytest

from runtime.tool_idempotency import run_json_tool_once, stable_json_hash
from storage.database import SessionLocal, init_database
from storage.repositories import get_tool_run


def test_run_json_tool_once_returns_stored_output_without_repeating_tool() -> None:
    init_database()
    session = SessionLocal()
    calls = {"count": 0}
    key = f"tool_once_{uuid4().hex}"
    try:
        def tool_fn():
            calls["count"] += 1
            return {"ok": True, "call": calls["count"]}

        first = run_json_tool_once(
            session,
            run_id="RUN-TOOL-1",
            tool_name="demo_tool",
            idempotency_key=key,
            input_json={"value": 1},
            tool_fn=tool_fn,
        )
        second = run_json_tool_once(
            session,
            run_id="RUN-TOOL-1",
            tool_name="demo_tool",
            idempotency_key=key,
            input_json={"value": 1},
            tool_fn=tool_fn,
        )

        assert first == {"ok": True, "call": 1}
        assert second == first
        assert calls["count"] == 1
        record = get_tool_run(session, key)
        assert record is not None
        assert record.status == "completed"
        assert record.input_hash == stable_json_hash({"value": 1})
    finally:
        session.close()


def test_run_json_tool_once_rejects_same_key_with_different_input() -> None:
    init_database()
    session = SessionLocal()
    key = f"tool_once_mismatch_{uuid4().hex}"
    try:
        run_json_tool_once(
            session,
            run_id="RUN-TOOL-2",
            tool_name="demo_tool",
            idempotency_key=key,
            input_json={"value": 1},
            tool_fn=lambda: {"ok": True},
        )

        with pytest.raises(ValueError, match="different input"):
            run_json_tool_once(
                session,
                run_id="RUN-TOOL-2",
                tool_name="demo_tool",
                idempotency_key=key,
                input_json={"value": 2},
                tool_fn=lambda: {"ok": False},
            )
    finally:
        session.close()
