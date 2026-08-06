from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


TRUTHY_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ConfigCheck:
    name: str
    status: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
        }


def configuration_status(
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    values = env or os.environ
    checks = [
        _database_check(values),
        _api_key_auth_check(values),
        _redis_check(values),
        _checkpoint_check(values),
        _openai_check(values),
        _roboflow_check(values),
        _live_scheduling_check(values),
    ]
    return {
        "overall_status": _overall_status(checks),
        "checks": [check.to_dict() for check in checks],
    }


def _database_check(env: Mapping[str, str]) -> ConfigCheck:
    database_url = env.get("DATABASE_URL", "sqlite:///artifacts/infra_agent.db")
    auto_create = env.get("AUTO_CREATE_DATABASE_TABLES", "true").lower() in TRUTHY_VALUES
    if database_url.startswith("sqlite:///"):
        return ConfigCheck(
            "database",
            "warning",
            "Using SQLite. Good for local development; use PostgreSQL for production.",
        )
    if database_url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        message = "PostgreSQL database URL is configured."
        if not auto_create:
            message += " Table auto-create is disabled; run Alembic migrations before startup."
        return ConfigCheck("database", "ok", message)
    return ConfigCheck(
        "database",
        "warning",
        "DATABASE_URL is configured, but it is not a recognized SQLite/PostgreSQL URL.",
    )


def _api_key_auth_check(env: Mapping[str, str]) -> ConfigCheck:
    auth_required = env.get("REQUIRE_API_KEY", "false").lower() in TRUTHY_VALUES
    if not auth_required:
        return ConfigCheck(
            "api_auth",
            "warning",
            "API key auth is disabled. Enable REQUIRE_API_KEY=true for shared demos.",
        )
    if env.get("INFRA_AGENT_API_KEY"):
        return ConfigCheck("api_auth", "ok", "API key auth is enabled and configured.")
    return ConfigCheck(
        "api_auth",
        "error",
        "REQUIRE_API_KEY=true but INFRA_AGENT_API_KEY is not set.",
    )


def _redis_check(env: Mapping[str, str]) -> ConfigCheck:
    redis_consumers = []
    for name in ("PROGRESS_STORE_BACKEND", "CACHE_STORE_BACKEND", "RATE_LIMIT_BACKEND"):
        if env.get(name, "memory").lower() == "redis":
            redis_consumers.append(name)
    if env.get("INSPECTION_JOB_BACKEND", "background").lower() == "rq":
        redis_consumers.append("INSPECTION_JOB_BACKEND")

    if not redis_consumers:
        return ConfigCheck(
            "redis",
            "warning",
            "Redis is not required by current env settings; runtime state is local/in-memory.",
        )
    if env.get("REDIS_URL"):
        return ConfigCheck(
            "redis",
            "ok",
            f"Redis URL is configured for {', '.join(redis_consumers)}.",
        )
    return ConfigCheck(
        "redis",
        "error",
        f"Redis-backed settings require REDIS_URL: {', '.join(redis_consumers)}.",
    )


def _checkpoint_check(env: Mapping[str, str]) -> ConfigCheck:
    backend = env.get("LANGGRAPH_CHECKPOINT_BACKEND", "memory").lower()
    if backend in {"", "none", "disabled"}:
        return ConfigCheck(
            "langgraph_checkpoint",
            "warning",
            "LangGraph checkpointing is disabled.",
        )
    if backend == "memory":
        return ConfigCheck(
            "langgraph_checkpoint",
            "warning",
            "Using in-memory LangGraph checkpoints; they do not survive process restarts.",
        )
    if backend == "sqlite":
        path = env.get("LANGGRAPH_CHECKPOINT_SQLITE_PATH", "artifacts/langgraph_checkpoints.sqlite")
        return ConfigCheck(
            "langgraph_checkpoint",
            "ok",
            f"SQLite LangGraph checkpoint path is configured at {path}.",
        )
    return ConfigCheck(
        "langgraph_checkpoint",
        "error",
        f"Unsupported LANGGRAPH_CHECKPOINT_BACKEND '{backend}'. Use memory, sqlite, or none.",
    )


def _openai_check(env: Mapping[str, str]) -> ConfigCheck:
    if env.get("OPENAI_API_KEY"):
        return ConfigCheck("openai", "ok", "OpenAI API key is configured.")
    return ConfigCheck(
        "openai",
        "warning",
        "OPENAI_API_KEY is not set. Use fake embeddings/deterministic modes for offline runs.",
    )


def _roboflow_check(env: Mapping[str, str]) -> ConfigCheck:
    has_api_key = bool(env.get("ROBOFLOW_API_KEY"))
    has_model = bool(env.get("ROBOFLOW_MODEL_ID") or env.get("ROBOFLOW_API_URL"))
    if has_api_key and has_model:
        return ConfigCheck("roboflow", "ok", "Roboflow detector credentials are configured.")
    if has_api_key or has_model:
        return ConfigCheck(
            "roboflow",
            "warning",
            "Roboflow is partially configured; set both API key and model/API URL.",
        )
    return ConfigCheck(
        "roboflow",
        "warning",
        "Roboflow is not configured. Use heuristic, metadata, or OpenAI image analysis.",
    )


def _live_scheduling_check(env: Mapping[str, str]) -> ConfigCheck:
    missing = []
    if not (env.get("OPENWEATHER_API_KEY") or env.get("OPEN_WEATHER_API_KEY")):
        missing.append("OPENWEATHER_API_KEY or OPEN_WEATHER_API_KEY")
    if not env.get("TOMTOM_API_KEY"):
        missing.append("TOMTOM_API_KEY")
    if env.get("EVENT_PROVIDER", "mock").lower() == "ticketmaster" and not env.get(
        "TICKETMASTER_API_KEY"
    ):
        missing.append("TICKETMASTER_API_KEY")

    if not missing:
        return ConfigCheck("live_scheduling", "ok", "Live scheduling provider keys are configured.")
    return ConfigCheck(
        "live_scheduling",
        "warning",
        "Missing optional live scheduling keys: " + ", ".join(missing) + ".",
    )


def _overall_status(checks: list[ConfigCheck]) -> str:
    if any(check.status == "error" for check in checks):
        return "error"
    if any(check.status == "warning" for check in checks):
        return "warning"
    return "ok"
