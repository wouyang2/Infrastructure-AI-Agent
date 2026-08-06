from __future__ import annotations

import sys
import types

import pytest

from agents.helpers.llm_runtime import llm_request_timeout_seconds
from agents.helpers.maintenance_plan_generator import LLMMaintenancePlanGenerator
from agents.helpers.report_generator import LLMReportGenerator
from agents.helpers.schedule_generator import LLMScheduleGenerator
from agents.helpers.severity_rationale_generator import LLMSeverityRationaleGenerator


def test_llm_request_timeout_defaults_to_30_seconds(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_REQUEST_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("OPENAI_SCHEDULING_TIMEOUT_SECONDS", raising=False)

    assert llm_request_timeout_seconds(env_name="OPENAI_SCHEDULING_TIMEOUT_SECONDS") == 30.0


def test_llm_request_timeout_uses_agent_specific_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_REQUEST_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("OPENAI_SCHEDULING_TIMEOUT_SECONDS", "7.5")

    assert llm_request_timeout_seconds(env_name="OPENAI_SCHEDULING_TIMEOUT_SECONDS") == 7.5


def test_llm_request_timeout_uses_shared_env(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_SCHEDULING_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("OPENAI_REQUEST_TIMEOUT_SECONDS", "12")

    assert llm_request_timeout_seconds(env_name="OPENAI_SCHEDULING_TIMEOUT_SECONDS") == 12.0


def test_llm_request_timeout_rejects_invalid_values(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_REQUEST_TIMEOUT_SECONDS", "0")

    with pytest.raises(ValueError, match="greater than 0"):
        llm_request_timeout_seconds(env_name="OPENAI_SCHEDULING_TIMEOUT_SECONDS")


def test_default_llm_generators_configure_timeouts(monkeypatch) -> None:
    fake_chat = FakeChatOpenAI()
    monkeypatch.setitem(
        sys.modules,
        "langchain_openai",
        types.SimpleNamespace(ChatOpenAI=fake_chat),
    )
    monkeypatch.setenv("OPENAI_SCHEDULING_TIMEOUT_SECONDS", "8")
    monkeypatch.setenv("OPENAI_REPORT_TIMEOUT_SECONDS", "9")
    monkeypatch.setenv("OPENAI_PLANNING_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("OPENAI_SEVERITY_TIMEOUT_SECONDS", "11")

    LLMScheduleGenerator()
    LLMReportGenerator()
    LLMMaintenancePlanGenerator()
    LLMSeverityRationaleGenerator()

    assert [call["timeout"] for call in fake_chat.calls] == [8.0, 9.0, 10.0, 11.0]
    assert [call["max_retries"] for call in fake_chat.calls] == [0, 0, 0, 0]


class FakeChatOpenAI:
    def __init__(self) -> None:
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return FakeStructuredRunnable()


class FakeStructuredRunnable:
    def with_structured_output(self, schema, *, method, strict):
        return self
