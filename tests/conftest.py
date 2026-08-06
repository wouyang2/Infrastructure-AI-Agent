from __future__ import annotations

import os


os.environ["INSPECTION_JOB_BACKEND"] = "background"
os.environ["PROGRESS_STORE_BACKEND"] = "memory"
os.environ["CACHE_STORE_BACKEND"] = "memory"
os.environ["RATE_LIMIT_BACKEND"] = "memory"
os.environ["LANGGRAPH_CHECKPOINT_BACKEND"] = "memory"
os.environ["INSPECTION_CRASH_MODE"] = "disabled"
