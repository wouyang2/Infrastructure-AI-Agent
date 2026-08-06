# Infrastructure AI Agent

Multi-agent AI prototype for bridge infrastructure inspection, severity assessment, maintenance planning, repair scheduling, and formal report generation.

## What It Does

- Accepts inspection notes, images, and videos.
- Detects bridge defects using heuristic, metadata, OpenAI, or Roboflow analyzers.
- Retrieves demo standards, manuals, repair records, and scheduling precedents through LangChain + Chroma RAG.
- Assesses severity and repair need.
- Builds maintenance plans from historical repair precedents.
- Schedules repair windows using RAG, LLM reasoning, and optional live weather, traffic, and event context.
- Provides a FastAPI UI with drag-and-drop image/video upload and formal report export.

## Main Components

- `agents/` - Intake, evidence, severity, maintenance planning, scheduling, and report agents.
- `rag/` - Retriever interfaces, fake embeddings, hierarchical chunking, and LangChain Chroma retriever.
- `workflows/` - LangGraph inspection workflow.
- `data/bridge_knowledge/` - Demo RAG corpus containing synthetic standards, manuals, repair records, and scheduling records.
- `evals/` - Dataset and detector evaluation scripts.
- `static/` - Browser UI for testing and presentation.
- `tests/` - Unit, integration, API, RAG, eval, and workflow tests.
- `docs/production-limitations.md` - Production limitation tracker and hardening roadmap.
- `docs/resume-project-summary.md` - Resume-oriented project summary and bullet points.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The base requirements use Roboflow's hosted HTTP API path. The optional
Roboflow local inference SDK currently conflicts with the Chroma dependency set
in this project, so it is split out:

```bash
pip install -r requirements-roboflow-inference.txt
```

Only install that optional file in a separate/local environment when you
specifically need `--roboflow-backend inference`. The Docker app should use the
default `auto` backend or `ROBOFLOW_BACKEND=http`.

Create a local `.env` file for optional live integrations:

```bash
DATABASE_URL=sqlite:///artifacts/infra_agent.db
AUTO_CREATE_DATABASE_TABLES=true
PROGRESS_STORE_BACKEND=memory
CACHE_STORE_BACKEND=memory
RATE_LIMIT_BACKEND=memory
INSPECTION_JOB_BACKEND=background
INSPECTION_RATE_LIMIT=100
INSPECTION_RATE_WINDOW_SECONDS=60
MAX_IMAGE_UPLOAD_BYTES=10485760
MAX_VIDEO_UPLOAD_BYTES=262144000
MEDIA_STORAGE_BACKEND=local
AWS_S3_MEDIA_BUCKET=
AWS_S3_MEDIA_PREFIX=inspection-media
AWS_S3_PRESIGN_EXPIRES_SECONDS=900
AWS_S3_DELETE_LOCAL_AFTER_UPLOAD=false
REQUIRE_API_KEY=false
INFRA_AGENT_API_KEY=change-me-for-protected-demo-runs
LANGGRAPH_CHECKPOINT_BACKEND=memory
LANGGRAPH_CHECKPOINT_SQLITE_PATH=artifacts/langgraph_checkpoints.sqlite
REDIS_URL=redis://localhost:6379/0
OPENAI_API_KEY=...
ROBOFLOW_API_KEY=...
ROBOFLOW_MODEL_ID=...
ROBOFLOW_BACKEND=http
OPEN_WEATHER_API_KEY=...
TOMTOM_API_KEY=...
TICKETMASTER_API_KEY=...
```

`.env` is intentionally ignored by git.

API key authentication is opt-in for local development. When
`REQUIRE_API_KEY=true`, protected API endpoints require either an `X-API-Key`
header or an `Authorization: Bearer ...` token matching `INFRA_AGENT_API_KEY`.
The browser UI includes an optional API key field and sends it as `X-API-Key`.
This is a production-aware guardrail, not a full user login or role-based
permission system yet.

The demo UI uploads image and video evidence with multipart `FormData` to avoid
base64-encoding large media in the browser. The API still keeps the older JSON
base64 upload endpoints for compatibility. Each upload creates an
`inspection_media` SQL metadata row with media ID, run linkage, MIME type, file
size, SHA-256 checksum, local storage key, preview URL, and scan status. The
media storage backend is configurable:

```bash
# default local development
MEDIA_STORAGE_BACKEND=local

# AWS S3 media storage
MEDIA_STORAGE_BACKEND=s3
AWS_S3_MEDIA_BUCKET=infra-agent-media-dev
AWS_REGION=us-east-1
AWS_S3_MEDIA_PREFIX=inspection-media
AWS_S3_PRESIGN_EXPIRES_SECONDS=900
```

With S3 enabled, uploaded media is written to the configured bucket and the SQL
row stores an `s3://...` file path plus a short-lived presigned preview URL.
For local S3-compatible development with MinIO, set `AWS_ENDPOINT_URL`.
Upload limits are controlled by `MAX_IMAGE_UPLOAD_BYTES` and
`MAX_VIDEO_UPLOAD_BYTES`.

### AWS S3 Media Setup

The project includes a boto3-based provisioning helper. It is dry-run by
default, so you can inspect the bucket name and IAM policy before creating
anything:

```bash
python3 scripts/aws/provision_s3_media.py \
  --region us-east-1 \
  --create-ecs-role
```

Apply the plan only after confirming the AWS caller/account is correct:

```bash
python3 scripts/aws/provision_s3_media.py \
  --region us-east-1 \
  --create-ecs-role \
  --apply
```

The script creates/configures:

- one private S3 bucket for inspection media
- S3 Block Public Access
- default server-side encryption
- a least-privilege IAM managed policy for the configured media prefix
- optionally, an ECS task role that can assume the policy later

After provisioning, configure the app:

```bash
MEDIA_STORAGE_BACKEND=s3
AWS_S3_MEDIA_BUCKET=infra-agent-media-<account>-us-east-1
AWS_REGION=us-east-1
AWS_S3_MEDIA_PREFIX=inspection-media
AWS_S3_PRESIGN_EXPIRES_SECONDS=900
```

Then run a small direct storage smoke test:

```bash
python3 scripts/aws/smoke_s3_media_upload.py
```

For local development, boto3 can use credentials from your AWS CLI profile,
`AWS_PROFILE`, or standard `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
environment variables. For production deployment, prefer IAM roles attached to
the running service rather than long-lived access keys.

The default local database is SQLite at `artifacts/infra_agent.db`. For
PostgreSQL, set `DATABASE_URL` to a SQLAlchemy URL such as:

```bash
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/infra_agent
```

Schema migrations are managed with Alembic. For local SQLite demos,
`AUTO_CREATE_DATABASE_TABLES=true` keeps startup convenient by creating missing
tables automatically. For production-style Postgres deployments, prefer:

```bash
AUTO_CREATE_DATABASE_TABLES=false
python3 -m storage.migrate upgrade
```

The Docker Compose stack includes a `postgres` service and a one-shot `migrate`
service that runs the Alembic upgrade before the API and RQ worker start. If
your `.env` already sets `DATABASE_URL=sqlite:///...`, Compose will keep using
SQLite; remove or replace that value to use the Compose Postgres service.

Progress tracking defaults to in-memory state for local development. To use
Redis for temporary workflow progress state, short-lived provider caches, and
shared API rate limits:

```bash
PROGRESS_STORE_BACKEND=redis
CACHE_STORE_BACKEND=redis
RATE_LIMIT_BACKEND=redis
REDIS_URL=redis://localhost:6379/0
```

Inspection jobs default to FastAPI background tasks, which is simple for local
development:

```bash
INSPECTION_JOB_BACKEND=background
```

For a Redis-backed worker queue, use RQ:

```bash
INSPECTION_JOB_BACKEND=rq
PROGRESS_STORE_BACKEND=redis
REDIS_URL=redis://localhost:6379/0
RQ_INSPECTION_QUEUE=inspection-jobs
RQ_INSPECTION_JOB_TIMEOUT_SECONDS=900
RQ_INSPECTION_RETRY_MAX_ATTEMPTS=3
RQ_INSPECTION_RETRY_INTERVALS_SECONDS=10,30,60
```

Then start a worker in another terminal:

```bash
rq worker --with-scheduler inspection-jobs --url redis://localhost:6379/0
```

With RQ, the API process only creates the SQL row and enqueues the job. The RQ
worker runs `runtime.inspection_jobs.execute_inspection_run`, updates progress,
and writes the final report back to SQL.
Completed inspection rows are guarded against late retry downgrades: if a job
with the same `run_id` runs after the row is already completed, the worker exits
without rewriting the completed report.
RQ retries are enabled by default for transient failures: the worker retries a
failed job 3 times after 10, 30, and 60 seconds. This reruns the inspection job;
the worker records a `job_attempt` progress event such as `attempt 2 of 4` when
running inside RQ. With a durable checkpoint backend, retries reuse the same
LangGraph `thread_id=run_id`. If the checkpoint has pending graph work, the
workflow resumes with `graph.invoke(None, config=...)` instead of starting again
with fresh input. Checkpoints are invoked with synchronous durability so the
latest completed step is flushed before the next node starts.
Use `--with-scheduler` on the worker because delayed retries are stored as
scheduled jobs before they move back to the active queue.

For a controlled RQ retry validation, copy the example crash settings file:

```bash
cp config/inspection_crash_settings.example.json config/inspection_crash_settings.json
```

Edit `config/inspection_crash_settings.json`:

```json
{
  "mode": "retryable",
  "stage": "severity",
  "status": "running",
  "marker_dir": "artifacts/crash_markers",
  "hard_exit_code": 70
}
```

Then start the worker. The worker auto-loads
`config/inspection_crash_settings.json` if the file exists:

```bash
export RQ_INSPECTION_RETRY_INTERVALS_SECONDS=3,10,30
export LANGGRAPH_CHECKPOINT_BACKEND=sqlite
export LANGGRAPH_CHECKPOINT_SQLITE_PATH=artifacts/langgraph_checkpoints.sqlite

rq worker --with-scheduler inspection-jobs --url redis://localhost:6379/0
```

Run one inspection through the UI. The worker records the `severity` progress
event, raises a retryable simulated crash once, RQ retries the same `run_id`,
and the second attempt should complete. Watch the flow in:

```text
App progress:  http://127.0.0.1:8001/
RQ Dashboard:  http://127.0.0.1:9181/
Case detail:   GET /cases/{run_id}
```

To disable crash simulation, set the file back to:

```json
{
  "mode": "disabled",
  "stage": "severity",
  "status": "running",
  "marker_dir": "artifacts/crash_markers",
  "hard_exit_code": 70
}
```

For a harder process-exit validation, set the file to:

```json
{
  "mode": "hard",
  "stage": "severity",
  "status": "running",
  "marker_dir": "artifacts/crash_markers",
  "hard_exit_code": 70
}
```

This records the matching progress event and then exits the worker process. Use
it to validate behavior closer to a killed worker/container. Restart the worker
with the same command after it exits. RQ should retry the same job ID and
complete the same `run_id`. The marker file prevents the retry from crashing at
the same stage forever. Older environment variables such as
`INSPECTION_SIMULATE_CRASH_AFTER_STAGE` still work, but the settings file is the
preferred local development path. To point at a different file, set
`INSPECTION_CRASH_SETTINGS_FILE=/path/to/settings.json`.
LangGraph checkpointing is enabled with `thread_id=run_id`, so graph state is
checkpointed under the inspection run ID. The default backend is `memory`, which
is useful for local development but does not survive process restarts. For a
more production-aware local setup, use SQLite checkpointing:

```bash
LANGGRAPH_CHECKPOINT_BACKEND=sqlite
LANGGRAPH_CHECKPOINT_SQLITE_PATH=artifacts/langgraph_checkpoints.sqlite
```

SQLite checkpointing requires `langgraph-checkpoint-sqlite` from
`requirements.txt`. It gives the graph a durable checkpoint store on disk, so an
RQ retry can point at the same `run_id` thread after a worker restart. A retry
can resume from the latest completed graph step; if a process dies in the middle
of a node, that node may run again because partial node output is not a valid
checkpoint.
Final report persistence is protected by a SQL `tool_runs` idempotency record:
`{run_id}:persist_inspection_report:v1`. If a retry reaches the same persistence
step again, the stored tool output is returned instead of writing the completed
inspection report twice.

## Run With Docker

This project now includes a Docker setup for Redis, the FastAPI app, and an RQ
worker. The Redis service is the actual Redis server used by progress tracking,
provider caching, rate limiting, and RQ job storage. It also includes an RQ
Dashboard service for monitoring queued, running, failed, and completed jobs.

Requires Docker Compose v2, where the command is `docker compose`.

```bash
docker compose up --build
```

Open:

```text
App:          http://127.0.0.1:8001/
RQ Dashboard: http://127.0.0.1:9181/
```

The compose stack runs:

```text
redis   -> Redis server with append-only persistence
api     -> FastAPI UI/API, submits inspection jobs
worker  -> RQ worker, executes inspection jobs
rq-dashboard -> RQ job dashboard connected to the same Redis queue
```

In Docker, `REDIS_URL` is `redis://redis:6379/0` because `redis` is the Compose
service name. Outside Docker, use `redis://localhost:6379/0`.

The dashboard is configured with `--disable-delete`, so it can monitor job
state without allowing job deletion from the UI. It is useful for seeing whether
an inspection is queued, running, failed, retried, or finished. It does not
replace LangSmith traces, workflow progress events, or SQL case history.

Be careful when running `docker compose config`: Docker expands `env_file`
values into the rendered config output. Do not paste that output publicly if
your local `.env` contains API keys.

The Docker image intentionally does not install Roboflow's optional
`inference` SDK because that package currently conflicts with Chroma's
`pybase64` requirement. Use `ROBOFLOW_BACKEND=http` in Docker.

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
GET /config/status
GET /cases
GET /cases/{run_id}
GET /cases/{run_id}/progress
GET /cases/{run_id}/events
GET /cases/{run_id}/review-events
PATCH /cases/{run_id}/review
POST /inspections
```

`GET /config/status` returns redacted runtime readiness checks for database,
auth, Redis, LangGraph checkpointing, OpenAI, Roboflow, and live scheduling
provider configuration. It reports whether secrets are configured, but never
returns secret values.

Each inspection request creates a durable `inspection_runs` database row, returns
a `run_id`, and then runs the workflow in a FastAPI background task. Clients
should treat `POST /inspections` as a job-submission endpoint:

```text
POST /inspections              -> returns run_id, status=queued
GET /cases/{run_id}/progress   -> live workflow progress
GET /cases/{run_id}/events     -> durable SQL workflow/retry history
GET /cases/{run_id}            -> completed report, status, errors, and review state
```

The database row stores request input, workflow status, severity, repair
decision, schedule window, report JSON, rendered report text, workflow trace
IDs, and human review status.
Live progress state is stored separately in memory or Redis because it is
optimized for UI polling, but durable progress/retry history is appended to
`inspection_run_events` in SQL.
Live scheduling provider responses can also use Redis as a short-lived cache
to reduce repeat OpenWeather, TomTom, and Ticketmaster calls.
The inspection endpoint also has a fixed-window rate limit. By default local
development allows 100 inspection runs per client per 60 seconds; tune
`INSPECTION_RATE_LIMIT` and `INSPECTION_RATE_WINDOW_SECONDS` for demos or
production.

Redis is used in three different runtime patterns:

- **Progress snapshot:** `infra_agent:progress:{run_id}` stores the latest node
  status and event list for live UI polling. The UI polls
  `GET /cases/{run_id}/progress` once per second while a run is active.
- **Durable run event log:** `inspection_run_events` stores workflow progress,
  checkpoint resume notices, RQ job attempts, failures, and completion in SQL.
  Use it to prove retry/crash behavior after Redis expires.
- **External API cache:** `infra_agent:cache:{provider}:{hash}` stores recent
  OpenWeather, TomTom, and Ticketmaster JSON responses with a 5-15 minute TTL.
  Example: the first weather request calls OpenWeather and stores the JSON; the
  next matching request within the TTL reads Redis and skips the external call.
- **Rate limit counter:** `infra_agent:rate_limit:{operation}:{client}:{window}`
  is incremented for each expensive inspection request and expires at the end of
  the window. If the counter exceeds the configured limit, the API returns
  `429 Too Many Requests` with a `Retry-After` header.
- **Job queue:** RQ stores pending inspection jobs in Redis lists and registries.
  The job payload contains the `run_id` and request data; SQL remains the source
  of truth for final inspection status and reports.
- **Tool idempotency:** SQL `tool_runs` records store stable tool
  `idempotency_key` values, input hashes, and completed outputs so side-effecting
  tools can return prior outputs during retries.

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
177 passed, 1 skipped, 1 warning
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
- **Normalize review and media persistence.** The project now has PostgreSQL-ready SQLAlchemy configuration and Alembic migrations, but reviewer edits, media lineage, and audit events should be moved into more normalized tables before real operational use.
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
- [x] Alembic migration setup with initial inspection/tool-run schema
- [x] Basic human review and approval workflow
- [x] Background inspection execution through FastAPI or RQ job submission
- [x] Redis-compatible progress state, live-context cache, and rate limiter with in-memory fallback
- [x] RQ Dashboard service for Docker job monitoring
- [x] Live UI workflow progress polling
- [x] Size-limited multipart image/video upload endpoints
- [x] SQL media metadata for uploaded inspection evidence
- [x] Unit and integration tests
- [x] Workflow run traces written to ignored JSON artifacts
- [x] Configurable LangGraph checkpoint backend with SQLite option
- [ ] Real maintenance and repair-history RAG corpus
- [x] Production-style PostgreSQL Compose service and Alembic migration path
- [ ] Authentication and role-based access
- [x] Redis Queue option for long video/vision processing
- [x] Basic SQL idempotency guard for duplicate completed inspection jobs
- [x] LangGraph checkpointing with stable run/thread IDs
- [x] SQL-backed tool-run idempotency for final report persistence
- [ ] Redis-backed distributed locks and job queues
- [ ] Editable human review workflow with reviewer identity and audit history
- [ ] Unified observability dashboard for traces, latency, cost, RAG quality, and failures
- [ ] Deployment hardening, secret management, and upload limits
- [ ] Production eval set built from real inspection cases

## Resume Summary

Built an end-to-end multi-agent AI system for bridge infrastructure inspection using LangGraph, FastAPI, LangChain, ChromaDB, OpenAI, Roboflow, OpenCV, OpenWeather, TomTom, and Ticketmaster. The system converts inspection evidence into structured observations, severity assessments, RAG-grounded maintenance plans, live-context repair schedules, and formal exportable inspection reports.
