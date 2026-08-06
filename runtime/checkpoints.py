from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from models import (
    Asset,
    Citation,
    EventContext,
    Evidence,
    HistoricalPrecedent,
    InspectionCase,
    InspectionReport,
    MaintenancePlan,
    MaintenanceTask,
    MediaReference,
    Observation,
    RepairSchedule,
    RepairWindow,
    SchedulingContext,
    SeverityAssessment,
    TrafficContext,
    WeatherContext,
)


CHECKPOINT_MSGPACK_ALLOWED_MODEL_TYPES = (
    Asset,
    Citation,
    EventContext,
    Evidence,
    HistoricalPrecedent,
    InspectionCase,
    InspectionReport,
    MaintenancePlan,
    MaintenanceTask,
    MediaReference,
    Observation,
    RepairSchedule,
    RepairWindow,
    SchedulingContext,
    SeverityAssessment,
    TrafficContext,
    WeatherContext,
)
CHECKPOINT_MSGPACK_ALLOWED_MODULES = tuple(
    (model_type.__module__, model_type.__name__)
    for model_type in CHECKPOINT_MSGPACK_ALLOWED_MODEL_TYPES
)
_CHECKPOINT_SERIALIZER = JsonPlusSerializer(
    allowed_msgpack_modules=CHECKPOINT_MSGPACK_ALLOWED_MODULES
)
_MEMORY_CHECKPOINTER = MemorySaver(serde=_CHECKPOINT_SERIALIZER)
DEFAULT_SQLITE_CHECKPOINT_PATH = "artifacts/langgraph_checkpoints.sqlite"
_SQLITE_CHECKPOINTERS: dict[str, Any] = {}
_SQLITE_CONTEXT_MANAGERS: dict[str, Any] = {}


def get_memory_checkpointer() -> MemorySaver:
    return _MEMORY_CHECKPOINTER


def get_checkpointer(
    *,
    backend: str | None = None,
    sqlite_path: str | None = None,
) -> Any:
    selected_backend = (backend or os.getenv("LANGGRAPH_CHECKPOINT_BACKEND", "memory")).lower()
    if selected_backend in {"", "none", "disabled"}:
        return None
    if selected_backend == "memory":
        return get_memory_checkpointer()
    if selected_backend == "sqlite":
        return get_sqlite_checkpointer(
            sqlite_path
            or os.getenv("LANGGRAPH_CHECKPOINT_SQLITE_PATH")
            or DEFAULT_SQLITE_CHECKPOINT_PATH
        )
    raise ValueError(
        "Unsupported LangGraph checkpoint backend "
        f"'{selected_backend}'. Use memory, sqlite, or none."
    )


def get_sqlite_checkpointer(sqlite_path: str) -> Any:
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as exc:
        raise RuntimeError(
            "SQLite LangGraph checkpointing requires the "
            "'langgraph-checkpoint-sqlite' package. Install requirements or use "
            "LANGGRAPH_CHECKPOINT_BACKEND=memory."
        ) from exc

    checkpoint_path = Path(sqlite_path)
    if checkpoint_path.parent != Path("."):
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    checkpoint_key = str(checkpoint_path)
    if checkpoint_key in _SQLITE_CHECKPOINTERS:
        return _SQLITE_CHECKPOINTERS[checkpoint_key]

    if hasattr(SqliteSaver, "from_conn_string"):
        saver_or_context = _build_sqlite_saver_from_conn_string(
            SqliteSaver,
            str(checkpoint_path),
        )
    else:
        saver_or_context = _build_sqlite_saver(SqliteSaver, str(checkpoint_path))

    if hasattr(saver_or_context, "__enter__") and hasattr(saver_or_context, "__exit__"):
        _SQLITE_CONTEXT_MANAGERS[checkpoint_key] = saver_or_context
        saver = saver_or_context.__enter__()
    else:
        saver = saver_or_context

    _SQLITE_CHECKPOINTERS[checkpoint_key] = saver
    return saver


def _build_sqlite_saver_from_conn_string(sqlite_saver_cls: Any, checkpoint_path: str) -> Any:
    try:
        return sqlite_saver_cls.from_conn_string(
            checkpoint_path,
            serde=_CHECKPOINT_SERIALIZER,
        )
    except TypeError:
        return sqlite_saver_cls.from_conn_string(checkpoint_path)


def _build_sqlite_saver(sqlite_saver_cls: Any, checkpoint_path: str) -> Any:
    try:
        return sqlite_saver_cls(checkpoint_path, serde=_CHECKPOINT_SERIALIZER)
    except TypeError:
        return sqlite_saver_cls(checkpoint_path)
