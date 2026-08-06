from __future__ import annotations

from runtime.config_validation import configuration_status


def _check_by_name(payload: dict[str, object], name: str) -> dict[str, str]:
    checks = payload["checks"]
    assert isinstance(checks, list)
    for check in checks:
        assert isinstance(check, dict)
        if check["name"] == name:
            return check
    raise AssertionError(f"Missing config check: {name}")


def test_configuration_status_reports_disabled_api_auth_warning() -> None:
    payload = configuration_status({})

    auth = _check_by_name(payload, "api_auth")
    assert payload["overall_status"] == "warning"
    assert auth["status"] == "warning"
    assert "disabled" in auth["message"]


def test_configuration_status_reports_missing_required_api_key() -> None:
    payload = configuration_status({"REQUIRE_API_KEY": "true"})

    auth = _check_by_name(payload, "api_auth")
    assert payload["overall_status"] == "error"
    assert auth["status"] == "error"
    assert "INFRA_AGENT_API_KEY" in auth["message"]


def test_configuration_status_reports_redis_requirement() -> None:
    payload = configuration_status({"INSPECTION_JOB_BACKEND": "rq"})

    redis = _check_by_name(payload, "redis")
    assert payload["overall_status"] == "error"
    assert redis["status"] == "error"
    assert "REDIS_URL" in redis["message"]


def test_configuration_status_reports_postgres_with_migrations() -> None:
    payload = configuration_status(
        {
            "DATABASE_URL": "postgres://infra_agent:secret@localhost:5432/infra_agent",
            "AUTO_CREATE_DATABASE_TABLES": "false",
        }
    )

    database = _check_by_name(payload, "database")
    assert database["status"] == "ok"
    assert "PostgreSQL" in database["message"]
    assert "Alembic migrations" in database["message"]
    assert "secret" not in str(payload)


def test_configuration_status_reports_memory_checkpoint_warning() -> None:
    payload = configuration_status({})

    checkpoint = _check_by_name(payload, "langgraph_checkpoint")
    assert checkpoint["status"] == "warning"
    assert "in-memory" in checkpoint["message"]


def test_configuration_status_reports_sqlite_checkpoint_configuration() -> None:
    payload = configuration_status(
        {
            "LANGGRAPH_CHECKPOINT_BACKEND": "sqlite",
            "LANGGRAPH_CHECKPOINT_SQLITE_PATH": "artifacts/test_checkpoints.sqlite",
        }
    )

    checkpoint = _check_by_name(payload, "langgraph_checkpoint")
    assert checkpoint["status"] == "ok"
    assert "artifacts/test_checkpoints.sqlite" in checkpoint["message"]


def test_configuration_status_does_not_expose_secret_values() -> None:
    payload = configuration_status(
        {
            "REQUIRE_API_KEY": "true",
            "INFRA_AGENT_API_KEY": "super-secret",
            "OPENAI_API_KEY": "sk-test-secret",
            "ROBOFLOW_API_KEY": "rf-secret",
            "ROBOFLOW_MODEL_ID": "bridge-defect/1",
        }
    )

    rendered = str(payload)
    assert "super-secret" not in rendered
    assert "sk-test-secret" not in rendered
    assert "rf-secret" not in rendered
