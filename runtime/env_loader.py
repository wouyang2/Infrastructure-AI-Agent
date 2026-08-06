from __future__ import annotations

import os
import sys


def load_dotenv_if_available() -> None:
    if _running_under_pytest() and os.getenv("INFRA_AGENT_LOAD_DOTENV_IN_TESTS") != "true":
        return

    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    load_dotenv()


def _running_under_pytest() -> bool:
    return (
        "pytest" in sys.modules
        or "PYTEST_CURRENT_TEST" in os.environ
        or "pytest" in os.path.basename(os.getenv("_", ""))
    )
