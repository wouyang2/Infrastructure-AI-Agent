from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from storage.repositories import (
    complete_tool_run,
    fail_tool_run,
    get_tool_run,
    start_tool_run,
)


def run_json_tool_once(
    session: Session,
    *,
    run_id: str,
    tool_name: str,
    idempotency_key: str,
    input_json: dict[str, Any],
    tool_fn: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Execute a side-effecting tool once for a stable idempotency key.

    Future LangGraph ToolNodes can wrap their external API calls or SQL writes
    with this helper. On retry, a completed tool returns its stored output
    instead of repeating the side effect.
    """
    input_hash = stable_json_hash(input_json)
    existing = get_tool_run(session, idempotency_key)
    if existing is not None:
        if existing.input_hash != input_hash:
            raise ValueError(
                "Idempotency key reuse with different input. "
                f"key={idempotency_key}"
            )
        if existing.status == "completed" and existing.output_json is not None:
            return dict(existing.output_json)

    record = start_tool_run(
        session,
        idempotency_key=idempotency_key,
        run_id=run_id,
        tool_name=tool_name,
        input_hash=input_hash,
        input_json=input_json,
    )
    try:
        output_json = tool_fn()
    except Exception as exc:
        fail_tool_run(session, idempotency_key=idempotency_key, error=str(exc))
        raise

    complete_tool_run(
        session,
        idempotency_key=idempotency_key,
        output_json=output_json,
    )
    return output_json


def stable_json_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
