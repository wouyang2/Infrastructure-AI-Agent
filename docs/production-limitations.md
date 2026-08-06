# Production Limitations Tracker

This document tracks what still separates the current Infrastructure AI Agent from a production inspection platform.

Current stage: production-aware MVP. The system demonstrates the full flow, but several components still need hardening before real operational use.

## Priority 0: Safety And Operational Guardrails

### Upload Limits And File Handling

- Status: partially complete
- Current limitation: uploads now support streamed multipart handling, SQL media metadata, and an opt-in S3 storage backend, but the project does not yet provision the real AWS bucket/IAM policy or perform content scanning.
- Target: enforce image/video upload size limits, reject oversized payloads early, and eventually move to streamed multipart uploads.
- Current progress: API rejects oversized image/video uploads with a clear `413` response. Limits are configurable with `MAX_IMAGE_UPLOAD_BYTES` and `MAX_VIDEO_UPLOAD_BYTES`. Backward-compatible base64 JSON upload endpoints remain available, and the demo UI now uses multipart `FormData` endpoints that stream image/video uploads in chunks. Each uploaded image/video creates an `inspection_media` SQL metadata row with media ID, run linkage, MIME type, file size, SHA-256 checksum, storage backend/key, preview URL, and scan status. `MEDIA_STORAGE_BACKEND=local` remains the default; `MEDIA_STORAGE_BACKEND=s3` writes uploaded media to `AWS_S3_MEDIA_BUCKET` using `boto3` and stores `s3://...` paths plus presigned preview URLs. The UI displays linked visual evidence in the overview and formal report preview.
- Remaining work: create the real AWS bucket and least-privilege IAM policy/role, decide whether previews should use direct presigned URLs or an API proxy, add antivirus/content scanning, and eventually deprecate base64 JSON upload endpoints.

### Authentication And Authorization

- Status: partial
- Current limitation: API key protection is available, but there is no real user login, session management, or role-based authorization.
- Target: add login, API authentication, and role-based permissions for inspector, engineer reviewer, and admin roles.
- Current progress: protected inspection, case history, review, upload, sample image, progress, and PDF export endpoints can require an API key when `REQUIRE_API_KEY=true`. Clients may send `X-API-Key` or `Authorization: Bearer ...`; the demo UI has an optional API key field.
- Remaining work: add identity-aware auth, role checks, review ownership, admin-only controls, and production token/session handling.
- Done means: every sensitive endpoint checks both authentication and authorization based on a real user identity.

### Secrets Management

- Status: partial
- Current limitation: `.env` is local-only and manually managed; deployment secret injection is documented but not enforced by infrastructure.
- Target: production secrets come from deployment environment or secret manager, not files committed or copied around.
- Current progress: `.env` is ignored by git, README documents runtime environment variables, Docker containers read secrets from the environment instead of baking them into images, and `GET /config/status` reports redacted readiness checks for auth, Redis, OpenAI, Roboflow, and live scheduling keys.
- Remaining work: move production credentials to a managed secret store or deployment secret mechanism, rotate any exposed keys, and convert runtime readiness checks into deployment/startup gates for production.
- Done means: documented secret injection for Docker/deployment and no secrets in repo or images.

## Priority 1: Durable Execution And Resume

### Durable LangGraph Checkpointing

- Status: partial
- Current limitation: LangGraph checkpointing is configurable and resume-aware invocation is implemented, but Docker revalidation after synchronous checkpoint durability is blocked by the local Docker Desktop storage error.
- Target: use durable SQLite/Postgres/Redis checkpoint storage.
- Current progress: graph construction now uses a checkpoint factory. `LANGGRAPH_CHECKPOINT_BACKEND=memory` keeps the old behavior, while `LANGGRAPH_CHECKPOINT_BACKEND=sqlite` uses `langgraph-checkpoint-sqlite` and `LANGGRAPH_CHECKPOINT_SQLITE_PATH` to persist graph checkpoints under the stable `run_id` thread. The workflow now checks `graph.get_state(config)` before invoking; if `snapshot.next` contains pending nodes, it resumes with `graph.invoke(None, config=...)` instead of starting from `START` with fresh input. Checkpoint invocation uses `durability="sync"` so completed node state is flushed before the next node starts. A graph-level test proves a retry after `severity` startup skips `intake` and `evidence`. The checkpoint serializer now explicitly allowlists project model dataclasses for msgpack deserialization to avoid future strict-mode blocking warnings.
- Remaining work: rerun Docker/RQ hard-crash validation after Docker Desktop storage is healthy and later consider Postgres/Redis checkpoint storage for distributed workers.
- Done means: a worker crash can resume from the latest persisted graph checkpoint instead of rerunning the whole graph.

### ToolNode Refactor

- Status: complete for the current graph path
- Current limitation: direct `EvidenceAgent` usage still keeps fallback analyzer/sampler calls for backwards compatibility, but the production graph path now routes expensive calls and final persistence through explicit tool nodes.
- Target: agents decide what tool to call; ToolNodes execute external calls and side effects.
- Current progress: scheduling RAG has been split into an explicit graph tool node, `schedule_precedent_tool`, between schedule-context collection and scheduling. The scheduling agent now consumes `scheduling_precedents` from graph state instead of retrieving them in the graph path. The tool node uses SQL `tool_runs` idempotency with a stable key derived from the run/case/plan inputs, so a completed scheduling precedent lookup can be reused on retry instead of repeating the RAG call. Schedule context collection is also now an idempotent tool boundary: weather, traffic, event, and access-risk context is serialized to JSON in `tool_runs` and reconstructed into `SchedulingContext` for downstream scheduling. Severity guidance RAG is now an explicit `severity_guidance_tool` node after evidence extraction; the severity agent consumes retrieved citations from graph state instead of retrieving them in the graph path. Maintenance repair-precedent RAG is now an explicit `maintenance_precedent_tool` on the repair-required branch; it stores both historical precedent objects and source repair documents for reuse by the planning agent. Visual evidence has been split into `video_frame_tool` for video sampling and `image_analysis_tool` for image/frame model inference. Report output has also been split: `report` assembles the report object, `annotated_artifact_tool` generates visual artifacts, `report_render_tool` renders deterministic or LLM-polished report text, and `persist_report_tool` writes the final case/report record to SQL.
- Remaining work: keep direct non-graph helper calls backwards compatible while treating the graph as the production execution path.
- Done means: graph contains explicit idempotent ToolNodes for RAG, vision, schedule context, report generation, and persistence.

### Tool-Level Idempotency Coverage

- Status: complete for the current graph path
- Current limitation: direct non-graph calls and some operator/admin actions are outside this coverage.
- Target: all side-effecting or expensive tools use stable idempotency keys and stored outputs.
- Current progress: final report persistence through `persist_report_tool`, video frame sampling, image/frame analysis, severity guidance RAG, maintenance repair-precedent RAG, schedule context collection, scheduling precedent RAG, annotated media generation, and report rendering use SQL idempotency records.
- Done means: retries do not duplicate external API calls, LLM calls, vision calls, or SQL writes when a completed tool output exists.

### RQ Retry And Failure Handling

- Status: partial
- Current limitation: RQ retry and scheduler-backed delayed retries are validated with both a controlled exception and hard worker process exit, but not yet with full container kill/restart orchestration.
- Target: connect RQ retries with durable checkpoints and clear retry metadata in progress UI.
- Current progress: inspection jobs pass `checkpoint_thread_id=run_id` and optional checkpoint backend settings into the workflow, so retries use the same LangGraph thread identity. RQ workers emit a `job_attempt` progress event with attempt count, max attempts, retries left, job ID, and worker name. Progress/retry events are now also appended to SQL in `inspection_run_events`, so crash-resume behavior can be inspected after Redis progress snapshots expire. The Docker worker now runs with `--with-scheduler`, which is required for delayed RQ retries to move from scheduled back to queued. Earlier Docker/RQ runs recovered from both a retryable exception and a hard worker work-horse exit. Resume-aware invocation and synchronous checkpoint durability were added afterward and pass local graph-level tests. A local Redis/RQ hard-failure run on 2026-08-02 recovered successfully: the first work-horse died, RQ retried the same `inspection-run_*` job after 10 seconds, LangGraph resumed from the SQLite checkpoint, and the same `run_id` completed successfully. The progress endpoint now overlays runtime RQ status, including queued/scheduled/started/failed status, retries left, worker name, and heartbeat, so the UI can distinguish "graph was last at scheduling" from "RQ is waiting to retry." Non-vision LLM calls now use configurable request timeouts and zero SDK-level retries by default, which prevents scheduling/report/planning/rationale stages from hanging indefinitely inside a worker attempt.
- Remaining work: rebuild and rerun hard-crash Docker/RQ validation after Docker Desktop recovers from its current BuildKit/containerd `EOF` and image-store input/output errors, validate recovery after killing/restarting the full worker container, and add an operator action for canceling or requeueing stale started jobs.
- Done means: failed transient jobs retry with visible attempt count and resume from durable checkpoint where possible.

## Priority 2: Production Persistence

### PostgreSQL Deployment

- Status: partial
- Current limitation: PostgreSQL deployment support exists, but it has not yet been exercised with a full Docker/RQ crash-recovery validation on this machine.
- Target: production database runs on PostgreSQL.
- Current progress: `psycopg` is included as the PostgreSQL driver, `DATABASE_URL` accepts `postgres://`, `postgresql://`, and `postgresql+psycopg://` forms, and Docker Compose includes a `postgres` service for production-style local deployment.
- Remaining work: run the full API/worker/RQ flow against Postgres after Docker Desktop is stable, then decide whether LangGraph checkpoints should also move from SQLite to a Postgres-backed checkpointer.
- Done means: deployment docs and env use `postgresql+psycopg://...`, and tests cover repository behavior independently from SQLite assumptions.

### Database Migrations

- Status: partial
- Current limitation: Alembic exists with the initial schema, but future schema changes still need to follow the migration workflow consistently.
- Target: add Alembic migrations.
- Current progress: added Alembic configuration, an initial migration for `inspection_runs` and `tool_runs`, and a `python3 -m storage.migrate upgrade` runner. Docker Compose runs the migration service before API/worker startup. `AUTO_CREATE_DATABASE_TABLES=false` can disable SQLAlchemy auto-create for production-style startup.
- Remaining work: replace the old lightweight SQLite patch path once existing local databases are either migrated or recreated, and add future migrations for normalized review/audit/media tables.
- Done means: schema changes are versioned and reproducible for SQLite/dev and PostgreSQL/prod.

### Audit Trail

- Status: partial
- Current limitation: review decision history and run progress/retry history are now captured, but report edits, defect corrections, media edits, and schedule overrides are not yet normalized as audit events.
- Target: record every human correction, approval, rejection, and report edit.
- Current progress: review updates append immutable rows to `inspection_review_events`, preserving previous status, new status, reviewer notes, reviewer identity, and timestamp. `GET /cases/{run_id}/review-events` exposes that history. Inspection workflow progress, RQ retry attempts, checkpoint resume notices, failures, and completion events append to `inspection_run_events`; `GET /cases/{run_id}/events` exposes that operational history.
- Remaining work: add audit events for edited observations, severity corrections, maintenance-plan changes, schedule overrides, final report edits, and approval metadata tied to real authenticated users.
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
- Current limitation: UI is suitable for demo/testing, not full operations. The browser can now submit additional inspections while another run is active and shows a lightweight inspection queue, but it is still not a full operations console.
- Target: case queues, filters, retry controls, trace viewer, annotated media review, editable recommendations, and user identity.
- Current progress: added an Inspection Queue panel to the demo UI. It uses existing `/cases` and `/cases/{run_id}/progress` endpoints to show active, retrying, completed, and failed runs together. The UI now keeps separate progress pollers per run and re-enables the submit button immediately after queueing, so another inspection can be submitted without waiting for the previous one to finish.
- Remaining work: add filters/search, operator retry/cancel/requeue controls, trace viewer, annotated media review, editable recommendations, document worker scaling, and move to authenticated multi-user operation before treating multi-worker concurrency as production-ready.
- Done means: engineer can manage multiple inspections from intake through approval.

### Observability

- Status: partial
- Current limitation: LangSmith, JSON workflow traces, API progress polling, and RQ Dashboard exist, but there is no unified dashboard for cost, latency, failures, and RAG quality.
- Target: production observability across API, worker, Redis/RQ, SQL, LLM calls, and RAG retrieval.
- Current progress: Docker Compose includes an `rq-dashboard` service on port `9181` connected to the same Redis queue as the worker. It can inspect queued, running, failed, retried, and completed inspection jobs, with destructive job deletion disabled.
- Remaining work: connect job status, workflow traces, LangSmith run IDs, SQL case records, latency percentiles, token/cost metrics, and RAG quality metrics into one operator view.
- Done means: operator can inspect slow/failing runs and understand where time/cost/error occurred.

### Docker/Deployment Verification

- Status: partial
- Current limitation: Docker Compose has been verified locally for the demo stack, but this is not yet a production deployment checklist.
- Target: verified local Docker Compose run and documented deployment checklist.
- Current progress: `docker compose up --build` rebuilt and started Redis, API, worker, and RQ Dashboard locally. The RQ worker with scheduler successfully processed delayed retries after both controlled failure and hard process-exit validation before the resume-aware invocation change. Docker Compose exposes both retryable-exception and hard-crash simulation environment variables for future regression checks. Docker images now exclude the large real bridge image binaries from `data/bridge_image/` while keeping CSV/JSON annotations, reducing build context size and avoiding accidental dataset baking.
- Remaining work: repair/restart Docker Desktop after its current BuildKit/containerd `EOF` and metadata/input-output errors, rerun the resume-aware hard-crash validation, document cleanup/restart flows, production secrets injection, health checks, backup/restore expectations, and full worker-container kill recovery validation.
- Done means: `docker compose up --build` starts Redis, API, worker, and RQ Dashboard successfully on a machine with Docker Compose v2 and the deployment checklist covers operational recovery.
