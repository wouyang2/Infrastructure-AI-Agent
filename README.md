# Infrastructure AI Agent

Multi-agent AI prototype for bridge infrastructure inspection, severity assessment, maintenance planning, repair scheduling, and formal report generation.

## What It Does

- Accepts inspection notes, images, and videos.
- Detects bridge defects using heuristic, metadata, OpenAI, or Roboflow analyzers.
- Retrieves demo standards, manuals, repair records, and scheduling precedents through LangChain + Chroma RAG.
- Assesses severity and repair need.
- Builds maintenance plans from historical repair precedents.
- Schedules repair windows using RAG, LLM reasoning, and optional live weather, traffic, and event context.
- Provides a FastAPI UI with drag-and-drop image upload and formal report export.

## Main Components

- `agents/` - Intake, evidence, severity, maintenance planning, scheduling, and report agents.
- `rag/` - Retriever interfaces, fake embeddings, hierarchical chunking, and LangChain Chroma retriever.
- `workflows/` - LangGraph inspection workflow.
- `data/bridge_knowledge/` - Demo RAG corpus containing synthetic standards, manuals, repair records, and scheduling records.
- `evals/` - Dataset and detector evaluation scripts.
- `static/` - Browser UI for testing and presentation.
- `tests/` - Unit, integration, API, RAG, eval, and workflow tests.
- `docs/resume-project-summary.md` - Resume-oriented project summary and bullet points.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a local `.env` file for optional live integrations:

```bash
OPENAI_API_KEY=...
ROBOFLOW_API_KEY=...
ROBOFLOW_MODEL_ID=...
OPEN_WEATHER_API_KEY=...
TOMTOM_API_KEY=...
TICKETMASTER_API_KEY=...
```

`.env` is intentionally ignored by git.

## Run The UI

```bash
python3 -m uvicorn api:app --host 127.0.0.1 --port 8001
```

Open:

```text
http://127.0.0.1:8001/
```

## Run The CLI

Offline-safe smoke run:

```bash
python3 main.py --embedding-backend fake --scheduling-mode deterministic
```

Live scheduling context:

```bash
python3 main.py \
  --embedding-backend fake \
  --schedule-context-mode live \
  --event-provider ticketmaster \
  --latitude 40.7505 \
  --longitude -73.9934
```

## Tests

```bash
python3 -m pytest -q
```

Latest status at cleanup:

```text
128 passed, 1 warning
```

## Data Note

The full raw bridge image dataset is not committed because it is large. Metadata and annotations can remain in the repository, while raw image files should be downloaded or restored locally as needed.

The current RAG knowledge corpus is intentionally demo-oriented. The files under `data/bridge_knowledge/` and `data/sample_knowledge.py` are synthetic or curated sample records used to validate the multi-agent workflow, RAG interfaces, citation flow, maintenance planning, and scheduling behavior. They should not be treated as authoritative infrastructure guidance.

When real data is available, the RAG index should be rebuilt from real sources such as:

- agency inspection manuals and repair standards
- historical work orders and repair records
- maintenance cost and duration logs
- lane closure and traffic control plans
- permit requirements and access restrictions
- scheduling outcomes, disruption notes, and crew availability records

Rebuild the persistent Chroma index after replacing the demo corpus:

```bash
python3 main.py \
  --embedding-backend openai \
  --knowledge-corpus bridge \
  --rebuild-rag-index
```

Generated artifacts are ignored:

- Chroma vector databases
- evaluation outputs
- uploaded images
- annotated images
- extracted video frames

## Current Limitations And Future Work

- The RAG corpus is synthetic/demo data; real maintenance records are needed for production-grade recommendations.
- Severity logic is still mostly rule-based, with LLM support focused on rationale rather than final authority.
- The Roboflow detector performance depends heavily on the trained model and dataset match.
- Scheduling uses live weather, traffic, and event APIs, but does not yet include real crew calendars, permit systems, or road-network closure simulation.
- PDF reports are generated, but future versions should include stronger evidence traceability, annotated image thumbnails, and video frame timelines.
- The UI is demo-focused; production use would need authentication, upload size limits, persistent case storage, audit logs, and deployment hardening.

## Resume Summary

Built an end-to-end multi-agent AI system for bridge infrastructure inspection using LangGraph, FastAPI, LangChain, ChromaDB, OpenAI, Roboflow, OpenCV, OpenWeather, TomTom, and Ticketmaster. The system converts inspection evidence into structured observations, severity assessments, RAG-grounded maintenance plans, live-context repair schedules, and formal exportable inspection reports.
