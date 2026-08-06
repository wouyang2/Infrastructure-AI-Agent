from __future__ import annotations

import os


DEFAULT_LLM_REQUEST_TIMEOUT_SECONDS = 30.0


def llm_request_timeout_seconds(
    *,
    env_name: str,
    default: float = DEFAULT_LLM_REQUEST_TIMEOUT_SECONDS,
) -> float:
    raw_value = os.getenv(env_name) or os.getenv("OPENAI_REQUEST_TIMEOUT_SECONDS")
    if raw_value is None:
        return default
    try:
        timeout = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a number of seconds.") from exc
    if timeout <= 0:
        raise ValueError(f"{env_name} must be greater than 0.")
    return timeout
