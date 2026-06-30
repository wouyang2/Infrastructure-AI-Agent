from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


class WorkflowTrace:
    def __init__(self, *, output_dir: str = "artifacts/traces"):
        self.trace_id = uuid4().hex
        self.output_dir = Path(output_dir)
        self.started_at = _utc_now()
        self.events: list[dict] = []

    def record_node(
        self,
        *,
        node_name: str,
        status: str,
        duration_ms: float,
        output_keys: list[str] | None = None,
        error: str | None = None,
    ) -> None:
        event = {
            "node": node_name,
            "status": status,
            "duration_ms": round(duration_ms, 3),
            "timestamp": _utc_now(),
        }
        if output_keys is not None:
            event["output_keys"] = output_keys
        if error:
            event["error"] = error
        self.events.append(event)

    def write(
        self,
        *,
        case_id: str,
        repair_required: bool | None,
        severity: str | None,
    ) -> str:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.output_dir / f"{case_id}_{self.trace_id}.json"
        payload = {
            "trace_id": self.trace_id,
            "case_id": case_id,
            "started_at": self.started_at,
            "finished_at": _utc_now(),
            "severity": severity,
            "repair_required": repair_required,
            "events": self.events,
        }
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return str(output_path)


def time_ms() -> float:
    return time.perf_counter() * 1000


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
