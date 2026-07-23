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
DATABASE_URL=sqlite:///artifacts/infra_agent.db
OPENAI_API_KEY=...
ROBOFLOW_API_KEY=...
ROBOFLOW_MODEL_ID=...
OPEN_WEATHER_API_KEY=...
TOMTOM_API_KEY=...
TICKETMASTER_API_KEY=...
```

`.env` is intentionally ignored by git.

The default local database is SQLite at `artifacts/infra_agent.db`. For
PostgreSQL, set `DATABASE_URL` to a SQLAlchemy URL such as:

```bash
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/infra_agent
```

## Run The UI

```bash
python3 -m uvicorn api:app --host 127.0.0.1 --port 8001
```

Open:

```text
http://127.0.0.1:8001/
```

Useful persistence endpoints:

```text
GET /cases
GET /cases/{run_id}
PATCH /cases/{run_id}/review
POST /inspections
```

Each inspection creates a durable `inspection_runs` database row with request
input, workflow status, severity, repair decision, schedule window, report JSON,
rendered report text, workflow trace IDs, and human review status.

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

Latest local status:

```text
135 passed, 1 warning
```

## Evaluation

Fast downstream baseline using annotation metadata as evidence:

```bash
python3 -m evals.bridge_dataset_eval \
  --limit 10 \
  --image-analyzer metadata \
  --embedding-backend fake \
  --scheduling-mode deterministic
```

RAG-only retrieval benchmark:

```bash
python3 -m evals.rag_retrieval_eval --embedding-backend fake
```

The RAG eval reports top-1 accuracy, top-k hit rate, wrong-defect retrieval rate,
average retrieved citations, and p50/p95/p99 retrieval latency. With LangSmith
tracing enabled, each retrieval appears as `RAG Search` and `RAG Document Lookup`
spans for query/filter/citation inspection.

Detector-only image benchmark:

```bash
python3 -m evals.roboflow_detector_eval --limit 10
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

The current project is a working prototype, not a production inspection platform. The most important future direction is to turn the demo intelligence into operational intelligence by replacing synthetic knowledge with real maintenance history and adding human review.

Recommended next improvements:

- **Replace synthetic RAG data with real infrastructure records.** Ingest real agency manuals, inspection standards, work orders, cost logs, repair durations, closure plans, permit rules, and post-repair outcomes. This is the highest-impact upgrade because maintenance planning and scheduling quality depend heavily on the knowledge base.
- **Improve severity assessment.** Current severity logic is mostly rule-based, with LLM support focused on rationale. Future versions should use defect size, bounding-box area, affected structural element, crack width, spall area, asset criticality, traffic importance, and LLM-assisted structured severity review.
- **Promote persistence to production Postgres.** Current local persistence uses SQLite with SQLAlchemy. Future versions should add Alembic migrations, production PostgreSQL deployment, and normalized tables for reviewer edits and media lineage.
- **Strengthen evidence traceability.** Add an evidence timeline showing notes, images, video frames, detector confidence, bounding boxes, RAG citations, and which agent used each piece of evidence.
- **Expand vision evaluation.** Continue evaluating the Roboflow detector with per-class precision/recall, confusion matrices, per-defect threshold tuning, and slices by lighting, camera angle, defect size, and distance.
- **Make scheduling more realistic.** Add crew calendars, equipment availability, permit lead times, lane closure constraints, detour impact, route/network effects, event calendars, weather windows, and repair-window optimization.
- **Improve the product UI.** Add case history, saved reports, side-by-side annotated media, video frame thumbnails, editable recommendations, and a one-click demo preset.
- **Harden deployment.** Add authentication, file size limits, secret management, background jobs for long video processing, observability, API rate-limit handling, and production logging.
- **Expand human-in-the-loop review.** The current UI supports case approval/rejection notes. Future versions should let engineers edit detected defects, severity, repair requirement, maintenance plan, schedule selection, and final PDF content before approval.

## Production Readiness Checklist

Current status: **production-aware MVP**. The system demonstrates the architecture and reliability patterns, but still needs real operational data and infrastructure before production use.

- [x] Typed multi-agent workflow with LangGraph
- [x] Image, video, and text evidence intake
- [x] Deterministic fallbacks for core decisions
- [x] RAG abstraction with Chroma-backed retrieval
- [x] Live weather, traffic, and event API integration
- [x] Formal PDF report export
- [x] SQLite persistence layer with PostgreSQL-ready SQLAlchemy configuration
- [x] Basic human review and approval workflow
- [x] Unit and integration tests
- [x] Workflow run traces written to ignored JSON artifacts
- [ ] Real maintenance and repair-history RAG corpus
- [ ] Production PostgreSQL deployment and Alembic migrations
- [ ] Authentication and role-based access
- [ ] Background job queue for long video/vision processing
- [ ] Redis-backed progress state, caching, rate limits, and distributed locks
- [ ] Editable human review workflow with reviewer identity and audit history
- [ ] Observability dashboard for traces, latency, cost, and failures
- [ ] Deployment hardening, secret management, and upload limits
- [ ] Production eval set built from real inspection cases

## Resume Summary

Built an end-to-end multi-agent AI system for bridge infrastructure inspection using LangGraph, FastAPI, LangChain, ChromaDB, OpenAI, Roboflow, OpenCV, OpenWeather, TomTom, and Ticketmaster. The system converts inspection evidence into structured observations, severity assessments, RAG-grounded maintenance plans, live-context repair schedules, and formal exportable inspection reports.
