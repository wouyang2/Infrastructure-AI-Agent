from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver


_MEMORY_CHECKPOINTER = MemorySaver()


def get_memory_checkpointer() -> MemorySaver:
    return _MEMORY_CHECKPOINTER
