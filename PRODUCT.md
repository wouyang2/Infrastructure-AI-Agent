# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The primary users are infrastructure inspectors, maintenance engineers, and operations reviewers who submit bridge inspection evidence, monitor long-running analysis, review the resulting engineering recommendations, and approve or export formal reports.

## Product Purpose

Infrastructure AI Agent turns inspection notes, images, and video into a traceable bridge-maintenance workflow. It extracts evidence, assesses severity, retrieves relevant standards and historical precedents, produces a maintenance plan, recommends a low-disruption repair window, and generates a reviewable report.

Success means an operator can start multiple inspections, understand the state of every run, inspect the evidence behind each recommendation, recover work after worker failures, and export a formal report without losing traceability.

## Positioning

The product combines multimodal defect evidence, hierarchical RAG, maintenance planning, real-time scheduling context, durable LangGraph execution, and formal reporting in one inspection case record. Recommendations remain connected to observations, retrieved sources, tool runs, and workflow events.

## Operating Context

Operators work from a desktop or field laptop. A typical workflow is to identify an asset, upload one image or video, add inspection notes, choose runtime providers, submit the inspection to an RQ worker, monitor progress, review observations and retrieved evidence, inspect the maintenance and scheduling recommendations, record a review decision, and optionally export a PDF.

Multiple inspections may be queued or reviewed during one session. The interface must retain access to active, completed, failed, and previously persisted runs.

## Capabilities and Constraints

- Accepts bridge inspection notes, image uploads, and video uploads.
- Supports heuristic, metadata, Roboflow, and OpenAI image analysis modes.
- Uses LangGraph agents and explicit tools for evidence, severity guidance, maintenance precedents, scheduling context, report rendering, and persistence.
- Uses Chroma-based RAG with standards, manuals, inspection reports, repair records, and scheduling precedents.
- Supports deterministic and LLM-assisted planning, scheduling, and reporting modes.
- Uses FastAPI, Redis, RQ, PostgreSQL, Alembic, and LangGraph checkpoints for production-aware execution.
- Exposes progress, durable workflow events, case details, review actions, and PDF export through existing API routes.
- Sample bridge images are development data and must not appear in the redesigned operator interface.
- Assumption from the redesign brief: multiple runs use a persistent run list with one selected run shown in a detailed tabbed workspace.

## Evidence on Hand

- Real annotated bridge images and COCO annotations under `data/bridge_image/`.
- Synthetic and curated knowledge records under `data/bridge_knowledge/` and `data/scheduling/`.
- Evaluation reports and runtime artifacts under `artifacts/` when generated.
- Existing API, workflow, persistence, crash-recovery, and UI tests under `tests/`.

The current knowledge corpus contains synthetic or prototype records and must not be presented as authoritative field guidance without human review.

## Product Principles

- Keep every recommendation traceable to evidence, retrieved sources, and workflow execution.
- Make long-running and recoverable work visible instead of hiding asynchronous state.
- Organize results by inspection run so operators never mix evidence between cases.
- Preserve human review and export as explicit operator choices.
- Communicate model and data limitations honestly.

## Accessibility & Inclusion

The web interface should support keyboard navigation, visible focus states, semantic controls, readable status text that does not rely on color alone, and responsive layouts for desktop and field-laptop widths.
