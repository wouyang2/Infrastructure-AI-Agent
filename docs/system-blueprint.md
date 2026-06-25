# Infrastructure AI Agent System Blueprint

## Product Goal

Build a multi-agent system that can inspect an infrastructure asset, assess repair severity, create a maintenance plan, and schedule repair work while minimizing disruption.

The first version should stay infrastructure-agnostic. Instead of hard-coding "bridge", "road", "building", or "pipeline" behavior, the system should use a shared asset model and domain-specific knowledge packs that can be swapped in later.

## Core Workflow

1. Intake an inspection request.
2. Collect inspection evidence from notes, images, videos, sensors, and historical records.
3. Retrieve relevant standards, prior inspections, asset history, manuals, and repair policies with RAG.
4. Assess condition and severity.
5. Decide whether repair is required.
6. Generate a maintenance plan.
7. Schedule repair work to reduce disruption.
8. Produce a traceable report with evidence, assumptions, and recommended next actions.

## Agent Roles

### 1. Intake Agent

Normalizes user input into a structured inspection case.

Responsibilities:
- Identify asset type, location, inspection reason, constraints, and available evidence.
- Ask for missing critical data.
- Create an initial `InspectionCase`.

### 2. Evidence Agent

Turns raw inspection inputs into usable observations.

Inputs may include:
- Human notes.
- Sensor readings.
- Images or videos.
- Historical work orders.
- Previous inspection reports.

Responsibilities:
- Run multimodal inspection over image and video evidence.
- Sample video frames and preserve timestamps for traceability.
- Extract defects, measurements, anomalies, and uncertainty.
- Attach each observation to its source.
- Flag missing or low-quality evidence.

For the first realistic version, image evidence should be supported before full video. Video can be handled by sampling key frames, running the same image inspection path, then aggregating frame-level observations into asset-level observations.

### 3. Retrieval Service / RAG Tool

Provides retrieval tools that other agents call when they need outside knowledge.

This is not a standalone decision-making agent in the first design. It is a shared service that exposes focused retrieval functions, such as `retrieve_policy_context`, `retrieve_asset_history`, and `retrieve_repair_precedents`. Agents should retrieve knowledge at the point where they need it, then include citations in their outputs.

Knowledge sources:
- Inspection manuals.
- Safety standards.
- Asset-specific maintenance policies.
- Historical repair records.
- Manufacturer guidance.
- Local regulatory requirements.

Responsibilities:
- Retrieve passages relevant to the observed defects and asset context.
- Rank retrieved evidence by authority and freshness.
- Provide citations to downstream agents.
- Keep retrieval separate from judgment. The retrieval service fetches evidence; domain agents interpret it.

Expected retrieval usage:
- Evidence Agent retrieves prior inspections and asset history to understand whether a defect is new, recurring, or worsening.
- Severity Agent retrieves inspection standards, safety thresholds, and regulatory guidance before assigning severity.
- Maintenance Planning Agent retrieves historical repair records, manuals, and maintenance policies before recommending a plan.
- Scheduling Agent retrieves prior disruption records, access constraints, and operational calendars when available.
- Report Agent does not usually retrieve new knowledge; it assembles and cites the evidence already used by earlier agents.

In a LangGraph implementation, retrieval should usually be represented as tools or graph nodes called by the agents that need them. A separate Retrieval Agent is only worth adding later if retrieval itself becomes complex enough to require planning, query rewriting, source selection, or result validation.

### 4. Severity Agent

Classifies condition and urgency.

Responsibilities:
- Compare observations against retrieved standards.
- Estimate severity, likelihood of failure, consequence of failure, and confidence.
- Decide whether the case needs repair, monitoring, emergency escalation, or no action.

Output:
- Severity level.
- Risk rationale.
- Confidence score.
- Evidence citations.

### 5. Maintenance Planning Agent

Creates a repair or monitoring plan.

Responsibilities:
- Recommend repair actions.
- Retrieve similar historical repairs using RAG.
- Compare possible repair strategies against past outcomes, cost, duration, recurrence, and disruption.
- Estimate required labor, materials, equipment, permits, access needs, and downtime.
- Break work into tasks.
- Identify dependencies and safety requirements.
- Explain which historical cases influenced the plan.

Historical repair retrieval should be separate from standards retrieval. Standards answer "what is allowed or required?" Historical repair data answers "what has worked for similar assets under similar conditions?"

### 6. Scheduling Agent

Chooses the best repair window.

Responsibilities:
- Minimize service disruption.
- Collect scheduling context from weather, traffic, city events/news, access constraints, and mock operational calendars.
- Respect crew availability, permits, traffic or occupancy patterns, asset criticality, and task dependencies.
- Rank candidate windows with deterministic scoring so the final decision is auditable.
- Produce a proposed schedule with tradeoffs.

Current implementation:
- Mock tools collect weather, traffic, city event/news, and access-risk context for each candidate window.
- The Scheduling Agent does not use an LLM to choose the window.
- Deterministic scoring combines disruption score, context risk, and urgency timing pressure so the selected window remains auditable.

### 7. Report Agent

Produces the final human-readable output.

Responsibilities:
- Summarize findings.
- Explain the repair decision.
- Include citations and confidence.
- Present the maintenance plan and schedule.
- List open assumptions and missing data.

## Shared Data Model

### Asset

```json
{
  "asset_id": "string",
  "asset_type": "bridge | road | building | pipeline | power_line | generic",
  "name": "string",
  "location": "string",
  "criticality": "low | medium | high | critical",
  "metadata": {}
}
```

### InspectionCase

```json
{
  "case_id": "string",
  "asset": {},
  "reason": "routine | complaint | sensor_alert | post_event | unknown",
  "evidence": [],
  "constraints": {},
  "created_at": "ISO-8601 timestamp"
}
```

### Observation

```json
{
  "observation_id": "string",
  "source_id": "string",
  "source_modality": "text | image | video_frame | sensor | record",
  "defect_type": "string",
  "description": "string",
  "location_on_asset": "string",
  "media_reference": {
    "file_path": "string",
    "frame_timestamp_seconds": 0,
    "bounding_box": [0, 0, 0, 0]
  },
  "measurement": {},
  "confidence": 0.0
}
```

### SeverityAssessment

```json
{
  "severity": "none | low | moderate | high | critical",
  "repair_required": true,
  "urgency": "monitor | scheduled | priority | emergency",
  "rationale": "string",
  "confidence": 0.0,
  "citations": []
}
```

### MaintenancePlan

```json
{
  "recommended_action": "string",
  "historical_precedents": [],
  "tasks": [],
  "materials": [],
  "equipment": [],
  "permits": [],
  "estimated_duration_hours": 0,
  "risks": []
}
```

### RepairSchedule

```json
{
  "recommended_window": {
    "start": "ISO-8601 timestamp",
    "end": "ISO-8601 timestamp"
  },
  "disruption_score": 0,
  "context_risk_score": 0,
  "total_score": 0,
  "constraints_satisfied": [],
  "tradeoffs": [],
  "context_summary": []
}
```

## RAG Design

RAG should support three kinds of retrieval:

1. Policy retrieval:
   - Standards, manuals, inspection rules, safety requirements.
   - Used by Severity and Maintenance Planning agents.

2. Case-history retrieval:
   - Previous inspections, work orders, defect trends, prior repairs.
   - Used by Evidence, Severity, Maintenance Planning, and Scheduling agents.

3. Historical repair retrieval:
   - Similar completed repairs, repair methods, crew notes, actual duration, actual cost, materials used, disruption impact, post-repair inspection outcomes, and recurrence.
   - Used mainly by the Maintenance Planning Agent.
   - Useful for turning a generic repair recommendation into a realistic plan.

The Maintenance Planning Agent should query historical repairs by:
- Asset type.
- Defect type.
- Severity level.
- Material or component.
- Operating context.
- Repair method.
- Outcome quality.
- Actual duration and disruption.

Recommended metadata for each chunk:
- `source_type`: standard, manual, inspection_report, work_order, regulation, asset_history, repair_record.
- `asset_type`.
- `defect_type`.
- `repair_method`.
- `severity`.
- `jurisdiction`.
- `effective_date`.
- `authority_level`.
- `asset_id`, when applicable.
- `repair_outcome`, when applicable.

Historical repair RAG should not blindly copy old repairs. It should retrieve precedents, then the planning agent should adapt them to the current asset, current standards, and current constraints.

## First Implementation Slice

Start with a text-only prototype, then add image and video evidence in stages:

1. User submits an inspection case with asset details and inspection notes.
2. System retrieves relevant knowledge from a small local document set.
3. Severity Agent classifies severity.
4. Maintenance Planning Agent generates a basic task plan.
5. Scheduling Agent chooses a repair window from mock availability data.
6. Report Agent returns a structured report.

This avoids premature complexity while the agent boundaries are still forming.

The next slice should add image input:

1. User submits asset details plus one or more inspection images.
2. Evidence Agent asks a vision model to identify visible defects, affected component, approximate location, and confidence.
3. Extracted visual observations flow into the same Severity, Maintenance Planning, Scheduling, and Report agents.

Current prototype status:
- The CLI accepts one or more `--image` inputs.
- The CLI accepts one or more `--video` inputs.
- Image evidence is represented as first-class evidence with media references.
- Real bridge image data is available in `data/bridge_image/` with normalized `metadata.csv` and `annotations.csv` generated from COCO annotations.
- Real annotated bridge images can be used with `--image-analyzer metadata`, which converts annotation rows into structured image findings with defect labels and bounding boxes.
- Video evidence is represented as sampled `video_frame` observations with timestamps.
- The Evidence Agent uses an injectable image analyzer.
- The CLI supports `--image-analyzer heuristic`, `--image-analyzer metadata`, and `--image-analyzer openai`.
- The CLI supports `--video-sampler mock` and `--video-sampler opencv`.
- OpenCV mode extracts timestamped JPEG frames into `artifacts/video_frames/`, which is ignored by Git.
- The default image analyzer is a deterministic local heuristic for tests and offline development.
- The optional OpenAI image analyzer uses `langchain_openai.ChatOpenAI` and returns structured image findings through the same analyzer interface.
- The inspection workflow now runs through a LangGraph state graph.
- Scheduling now has a mock context collection node composed of weather, traffic, city event/news, and access-risk tools.
- The final schedule is still selected by deterministic scoring for auditability.
- The graph now branches after severity: repair-required cases continue to maintenance planning and scheduling, while monitoring-only cases skip repair scheduling.
- Maintenance planning now supports `--planning-mode deterministic` and opt-in `--planning-mode llm`.
- LLM planning uses `langchain_openai.ChatOpenAI.with_structured_output(...)` to adapt retrieved repair precedents into a structured maintenance plan.
- LLM planning retries are controlled by `--llm-max-retries`; exhausted retries can either fall back with a visible risk note or fail the pipeline via `--llm-failure-mode`.
- Severity assessment now supports `--severity-mode deterministic` and opt-in `--severity-mode llm`.
- LLM severity mode does not decide severity, urgency, repair requirement, or confidence; it only rewrites the rationale and notes missing evidence from the deterministic assessment and citations.
- Report rendering now supports `--report-mode deterministic` and opt-in `--report-mode llm`.
- LLM report mode polishes the final Markdown report from deterministic structured outputs and must preserve factual values, citation IDs, schedule windows, scores, and decisions.
- A FastAPI wrapper exposes the workflow through `GET /health` and `POST /inspections`.
- The default RAG layer now uses persistent `langchain_chroma` in `artifacts/chroma` with OpenAI embeddings.
- The CLI supports `--rag-backend chroma|local`, `--embedding-backend fake|openai`, `--embedding-model`, `--chroma-persist-dir`, and `--rebuild-rag-index`.
- The CLI supports `--knowledge-corpus sample|bridge|merged`; `merged` is the default and combines stable sample fixtures with generated bridge standards, manuals, inspection reports, and repair records.
- The Chroma retriever uses parent chunks, overlapping child chunks, and semantic sibling merge before returning citations.
- `text-embedding-3-small` is the default OpenAI embedding model through `langchain_openai.OpenAIEmbeddings`.
- The older lexical retriever remains available through `--rag-backend local` as a fallback/dev reference.
- `python3 -m evals.bridge_dataset_eval` runs the bridge image dataset eval and writes JSON/Markdown summaries to `artifacts/evals`.
- The eval supports `--image-analyzer metadata|heuristic|openai`; metadata is the annotation-assisted baseline, while OpenAI/heuristic modes measure image inference against annotation ground truth.

The current video slice supports prototype-safe and real local video input:

1. User submits inspection video.
2. Mock mode creates deterministic frame references at fixed timestamps.
3. OpenCV mode extracts real frames at configurable intervals.
4. Evidence Agent analyzes each sampled frame.
5. Frame-level observations preserve timestamps.
6. Downstream agents receive consolidated observations.

Future video work should add duplicate-frame aggregation and scene-change sampling.

## Suggested Initial Tech Stack

- Python for agent orchestration and backend logic.
- LangGraph for the multi-agent workflow graph and state transitions.
- LangChain for model wrappers, retrievers, prompt templates, and document loaders.
- `langchain_openai` for OpenAI model access.
- `langchain_chroma` plus `chromadb` for Chroma-backed vector search.
- Pydantic for shared schemas and graph state validation.
- FastAPI for an API later.
- Chroma for local vector search.
- SQLite for prototype case storage.
- OpenCV or PyAV for video frame sampling.
- OpenAI API for optional multimodal image analysis.
- A deterministic scheduling heuristic before adding optimization solvers.

## LangGraph Workflow Shape

The prototype should evolve from a linear Python pipeline into a LangGraph state graph:

```text
Intake
  -> Evidence Extraction
  -> RAG Retrieval
  -> Severity Assessment
  -> if repair_required:
       Maintenance Planning
       -> Scheduling
     else:
       Monitoring Plan
  -> Report
```

Suggested graph state:

```json
{
  "inspection_case": {},
  "media_assets": [],
  "observations": [],
  "retrieved_policy_context": [],
  "retrieved_repair_history": [],
  "severity_assessment": {},
  "maintenance_plan": {},
  "scheduling_context": {},
  "repair_schedule": {},
  "report": "string"
}
```

LangGraph is a good fit because repair planning has conditional branches, retries, and human-review checkpoints. LangChain is useful underneath the graph for RAG, model calls, document loading, and prompt composition.

Current graph nodes:
- `intake`
- `evidence`
- `severity`
- `maintenance_planning`
- `monitoring_plan`
- `schedule_context`
- `scheduling`
- `report`

## Open Decisions

- Which infrastructure domain should be the first target?
- Which documents should seed the first RAG knowledge base?
- Should the prototype run as a CLI first, API first, or web app first?
- Which LLM provider should be used?
- How strict should severity classification be: rule-based, model-based, or hybrid?

## Recommended Next Step

Choose the first vertical slice:

**Generic text-only inspection prototype**

This lets us prove the multi-agent flow and RAG grounding before choosing a specific infrastructure domain.
