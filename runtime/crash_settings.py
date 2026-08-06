from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


CrashMode = Literal["disabled", "retryable", "hard"]


@dataclass(frozen=True)
class CrashSimulationSettings:
    mode: CrashMode = "disabled"
    stage: str | None = None
    status: str = "running"
    marker_dir: str = "artifacts/crash_markers"
    hard_exit_code: int = 70

    @property
    def enabled(self) -> bool:
        return self.mode != "disabled" and bool(self.stage)


def load_crash_simulation_settings() -> CrashSimulationSettings:
    file_settings = _load_file_settings()
    return CrashSimulationSettings(
        mode=_crash_mode(
            _first_configured(
                os.getenv("INSPECTION_CRASH_MODE"),
                _legacy_env_mode_if_enabled(),
                file_settings.get("mode"),
                "disabled",
            )
        ),
        stage=_first_configured(
            os.getenv("INSPECTION_CRASH_STAGE"),
            _legacy_env_stage(),
            file_settings.get("stage"),
        ),
        status=str(
            _first_configured(
                os.getenv("INSPECTION_CRASH_ON_STATUS"),
                _legacy_env_status_if_enabled(),
                file_settings.get("status"),
                "running",
            )
        ),
        marker_dir=str(
            _first_configured(
                os.getenv("INSPECTION_CRASH_MARKER_DIR"),
                file_settings.get("marker_dir"),
                "artifacts/crash_markers",
            )
        ),
        hard_exit_code=int(
            _first_configured(
                os.getenv("INSPECTION_HARD_CRASH_EXIT_CODE"),
                file_settings.get("hard_exit_code"),
                "70",
            )
        ),
    )


def _load_file_settings() -> dict[str, Any]:
    settings_path = os.getenv("INSPECTION_CRASH_SETTINGS_FILE", "config/inspection_crash_settings.json")
    path = Path(settings_path)
    if not path.exists() and not os.getenv("INSPECTION_CRASH_SETTINGS_FILE"):
        return {}

    if not path.exists():
        raise FileNotFoundError(f"Crash settings file not found: {path}")

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Crash settings file is not valid JSON: {path}") from exc

    if not isinstance(loaded, dict):
        raise ValueError(f"Crash settings file must contain a JSON object: {path}")
    return loaded


def _first_configured(*values: Any) -> Any:
    for value in values:
        if value not in {None, ""}:
            return value
    return None


def _crash_mode(value: Any) -> CrashMode:
    mode = str(value or "disabled").lower()
    if mode in {"off", "none", "false", "disabled"}:
        return "disabled"
    if mode in {"retry", "retryable", "exception"}:
        return "retryable"
    if mode in {"hard", "exit", "process_exit"}:
        return "hard"
    raise ValueError(
        "Unsupported crash simulation mode "
        f"'{value}'. Use disabled, retryable, or hard."
    )


def _legacy_env_mode() -> str:
    if os.getenv("INSPECTION_SIMULATE_HARD_CRASH_AFTER_STAGE"):
        return "hard"
    if os.getenv("INSPECTION_SIMULATE_CRASH_AFTER_STAGE"):
        return "retryable"
    return "disabled"


def _legacy_env_mode_if_enabled() -> str | None:
    mode = _legacy_env_mode()
    return mode if mode != "disabled" else None


def _legacy_env_stage() -> str | None:
    return os.getenv("INSPECTION_SIMULATE_HARD_CRASH_AFTER_STAGE") or os.getenv(
        "INSPECTION_SIMULATE_CRASH_AFTER_STAGE"
    )


def _legacy_env_status() -> str:
    return (
        os.getenv("INSPECTION_SIMULATE_HARD_CRASH_ON_STATUS")
        or os.getenv("INSPECTION_SIMULATE_CRASH_ON_STATUS")
        or "running"
    )


def _legacy_env_status_if_enabled() -> str | None:
    return _legacy_env_status() if _legacy_env_mode_if_enabled() else None
