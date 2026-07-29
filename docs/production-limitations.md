# Production Limitations Tracker

This document tracks what still separates the current Infrastructure AI Agent from a production inspection platform.

Current stage: production-aware MVP. The system demonstrates the full flow, but several components still need hardening before real operational use.

## Priority 0: Safety And Operational Guardrails

### Upload Limits And File Handling

- Status: partially complete
- Current limitation: uploads are base64 JSON payloads with only extension and basic image validation. Large files could consume too much memory or disk.
- Target: enforce image/video upload size limits, reject oversized payloads early, and eventually move to streamed multipart uploads.
- Current progress: API rejects oversized image/video uploads with a clear `413` response. Limits are configurable with `MAX_IMAGE_UPLOAD_BYTES` and `MAX_VIDEO_UPLOAD_BYTES`.
- Remaining work: move large media upload to streamed multipart handling instead of base64 JSON.

### Authentication And Authorization

- Status: not started
- Current limitation: UI/API endpoints are open.
- Target: add login, API authentication, and role-based permissions for inspector, engineer reviewer, and admin roles.
- Done means: protected inspection, case history, review, export, and admin endpoints.

### Secrets Management

- Status: not started
- Current limitation: `.env` is local-only and manually managed.
- Target: production secrets come from deployment environment or secret manager, not files committed or copied around.
- Done means: documented secret injection for Docker/deployment and no secrets in repo or images.

## Priority 1: Durable Execution And Resume

### Durable LangGraph Checkpointing

- Status: partial
- Current limitation: LangGraph uses memory checkpointing with `thread_id=run_id`, which does not survive container restarts.
- Target: use durable SQLite/Postgres/Redis checkpoint storage.
- Done means: a worker crash can resume from the latest persisted graph checkpoint instead of rerunning the whole graph.

### ToolNode Refactor

- Status: partial
- Current limitation: many tools are still embedded inside agent classes. Final report persistence has SQL idempotency, but RAG, vision, weather, traffic, event, and report-generation calls are not yet explicit ToolNodes.
- Target: agents decide what tool to call; ToolNodes execute external calls and side effects.
- Done means: graph contains explicit idempotent ToolNodes for RAG, vision, schedule context, report generation, and persistence.

### Tool-Level Idempotency Coverage

- Status: partial
- Current limitation: SQL `tool_runs` infrastructure exists, but only final report persistence uses it.
- Target: all side-effecting or expensive tools use stable idempotency keys and stored outputs.
- Done means: retries do not duplicate external API calls, LLM calls, vision calls, or SQL writes when a completed tool output exists.

### RQ Retry And Failure Handling

- Status: partial
- Current limitation: RQ retry is configured, but retries rerun the job rather than resuming from a durable graph checkpoint.
- Target: connect RQ retries with durable checkpoints and clear retry metadata in progress UI.
- Done means: failed transient jobs retry with visible attempt count and resume from durable checkpoint where possible.

## Priority 2: Production Persistence

### PostgreSQL Deployment

- Status: not started
- Current limitation: local default is SQLite.
- Target: production database runs on PostgreSQL.
- Done means: deployment docs and env use `postgresql+psycopg://...`, and tests cover repository behavior independently from SQLite assumptions.

### Database Migrations

- Status: not started
- Current limitation: lightweight SQLite migrations are hand-written for demo fields.
- Target: add Alembic migrations.
- Done means: schema changes are versioned and reproducible for SQLite/dev and PostgreSQL/prod.

### Audit Trail

- Status: not started
- Current limitation: review state exists, but reviewer edits and decision history are not normalized.
- Target: record every human correction, approval, rejection, and report edit.
- Done means: case review history can explain who changed what, when, and why.

## Priority 3: Data And Model Quality

### Real RAG Corpus

- Status: not started
- Current limitation: bridge knowledge corpus contains demo/synthetic standards, manuals, repair records, and scheduling records.
- Target: replace with real agency manuals, inspection standards, work orders, closure plans, repair durations, costs, and post-repair outcomes.
- Done means: RAG eval uses real documents and real historical repair records.

### Continuous Evaluation

- Status: partial
- Current limitation: local eval scripts exist, but production monitoring and scheduled evals are not automated.
- Target: scheduled evals for vision, RAG retrieval, severity, scheduling, and report quality.
- Done means: evals run from CI or a scheduled job and write comparable reports over time.

### Human Feedback Loop

- Status: not started
- Current limitation: human review does not feed back into RAG updates or model calibration.
- Target: approved/corrected inspection cases become candidates for future RAG entries and calibration datasets.
- Done means: reviewed cases can be exported into curated training/RAG datasets.

## Priority 4: Product And Deployment

### UI For Operations

- Status: partial
- Current limitation: UI is suitable for demo/testing, not full operations.
- Target: case queues, filters, retry controls, trace viewer, annotated media review, editable recommendations, and user identity.
- Done means: engineer can manage multiple inspections from intake through approval.

### Observability

- Status: partial
- Current limitation: LangSmith and JSON workflow traces exist, but no unified dashboard for jobs, cost, latency, failures, and RAG quality.
- Target: production observability across API, worker, Redis/RQ, SQL, LLM calls, and RAG retrieval.
- Done means: operator can inspect slow/failing runs and understand where time/cost/error occurred.

### Docker/Deployment Verification

- Status: partial
- Current limitation: Docker files exist, but Compose was not verified on this machine because Docker Compose is not installed.
- Target: verified local Docker Compose run and documented deployment checklist.
- Done means: `docker compose up --build` starts Redis, API, and worker successfully on a machine with Docker Compose v2.
