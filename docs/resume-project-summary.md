# Infrastructure AI Agent - Project Summary

## Overview

Infrastructure AI Agent is a multi-agent inspection and maintenance planning system for bridge infrastructure. The project takes inspection evidence from text, images, and video frames, identifies infrastructure defects, evaluates severity, retrieves relevant technical guidance and historical repair cases, produces a maintenance plan, schedules repairs around live disruption factors, and generates a formal inspection report for presentation or export.

The system was designed as an end-to-end applied AI prototype with practical infrastructure workflows in mind: defect detection, severity assessment, repair planning, scheduling, traceability, and human-readable reporting.

## Core Capabilities

- Processes inspection notes, uploaded images, annotated bridge datasets, and sampled video frames.
- Detects bridge defects including cracks, spalling, corrosion, exposed rebar, efflorescence/leak-style staining, and unknown/no-defect cases.
- Uses Roboflow-hosted bridge defect detection and optional OpenAI vision verification.
- Assesses severity and repair requirement using deterministic decision logic with LLM-supported rationale paths.
- Retrieves standards, manuals, historical repair records, and scheduling precedents using LangChain + Chroma RAG.
- Builds maintenance plans using retrieved repair precedents and optional LLM planning.
- Schedules repair windows using live weather, traffic, and event context.
- Generates a formal report preview with optional LLM-polished narrative and browser-based PDF export.
- Provides a FastAPI-backed demo UI with drag-and-drop image upload and sample bridge image selection.

## Multi-Agent Architecture

The workflow is implemented as a LangGraph-style agent pipeline:

1. **Intake Agent**
   - Creates an inspection case from asset metadata, notes, images, videos, and location.
   - Supports latitude/longitude metadata for live scheduling context.

2. **Evidence Agent**
   - Extracts observations from text, image, and video evidence.
   - Supports heuristic, metadata, OpenAI, and Roboflow image analyzers.
   - Supports OpenCV video frame sampling for real video inputs.

3. **Severity Agent**
   - Determines severity, urgency, and whether repair is required.
   - Uses deterministic rules for auditable decisions.
   - Supports LLM-generated rationale without replacing deterministic severity control.

4. **Maintenance Planning Agent**
   - Uses RAG over standards and historical repair records.
   - Generates repair tasks, materials, equipment, permits, risks, and duration estimates.
   - Supports opt-in LLM structured plan generation with fallback controls.

5. **Scheduling Agent**
   - Uses RAG scheduling precedents plus live operational context.
   - Pulls weather from OpenWeather, traffic from TomTom, and event conflicts from Ticketmaster.
   - Uses LLM scheduling by default with deterministic scoring and validation.
   - Reranks scheduling precedents by asset type, defect type, repair method, crew type, duration, and outcome.

6. **Report Agent**
   - Produces deterministic reports by default for reliability.
   - Supports LLM-polished report prose for presentation.
   - Feeds structured output into a formal report preview rather than exposing raw Markdown.

## RAG System

The RAG layer evolved from a simple local lexical retriever into a persistent LangChain Chroma retriever.

Key RAG features:

- LangChain Chroma vector store.
- Persistent Chroma database under `artifacts/chroma`.
- OpenAI embeddings by default with deterministic fake embeddings for tests.
- Parent/child hierarchical chunking:
  - Parent chunks around 1200 characters.
  - Child chunks around 450 characters with overlap.
- Semantic child merge to combine related sibling chunks.
- Metadata filters for:
  - `source_type`
  - `asset_type`
  - `defect_type`
- Corpus includes:
  - standards
  - manuals
  - inspection reports
  - historical repair records
  - scheduling records

The agents consume RAG through a stable interface:

```python
search(...) -> list[Citation]
get_document(document_id) -> dict | None
```

This allows the retriever implementation to evolve without changing agent interfaces.

## Vision Pipeline

The project includes several image analysis modes:

- **Heuristic Analyzer**
  - Offline fallback for tests and quick development.

- **Metadata Analyzer**
  - Uses annotated dataset metadata for deterministic evaluation.

- **OpenAI Image Analyzer**
  - Uses OpenAI multimodal analysis for structured defect findings.

- **Roboflow Image Analyzer**
  - Uses a hosted bridge defect detection model through Roboflow.
  - Supports class threshold tuning and class mapping.

- **Verified Image Analyzer**
  - Combines detector results with OpenAI verification for ambiguous cases.
  - Helps reduce false positives and improve confidence in defect labels.

Video support was added through OpenCV:

- Extracts timestamped frames from video.
- Saves frames to `artifacts/video_frames`.
- Reuses the image analysis path for each sampled frame.

## Live Scheduling Integrations

The Scheduling Agent uses live operational context when enabled:

- **OpenWeather API**
  - Forecast condition, precipitation probability, wind, and weather risk.

- **TomTom Traffic API**
  - Current speed, free-flow speed, travel time, closure status, and traffic risk.

- **Ticketmaster Discovery API**
  - Nearby events around the repair location and repair window.
  - Used as a free/simple event conflict source.

The live context is opt-in through the UI/API and can fall back to deterministic mock context for repeatable development and testing.

## User Interface

The project includes a FastAPI-served frontend for testing and presentations.

UI features:

- Drag-and-drop image upload.
- Sample bridge image strip from the annotated dataset.
- Analyzer mode selection.
- Fake/OpenAI embedding selection.
- Deterministic/LLM planning selection.
- Deterministic/LLM scheduling selection.
- Mock/live scheduling context selection.
- Formal report preview.
- Export report button using browser PDF export.
- Summary cards for severity, repair decision, schedule, and context risk.
- Panels for observations, RAG citations, scheduling context, and maintenance plan.

The UI is served at:

```text
http://127.0.0.1:8001/
```

## Evaluation And Testing

The project includes an evaluation-focused development process:

- Bridge dataset eval over annotated bridge images.
- Roboflow detector threshold evaluation.
- Vision verifier experiments with OpenAI.
- Reviewed taxonomy support for visually ambiguous labels.
- RAG retrieval tests for standards, repair precedents, and scheduling precedents.
- Graph-level tests proving correct workflow sequencing.
- API tests for UI, uploads, inspections, and sample image feeds.
- Offline tests using fake embeddings and mocked LLM/API clients.

Latest test suite status at pause:

```text
125 passed, 1 warning
```

## Technical Stack

- Python
- FastAPI
- LangGraph
- LangChain
- LangChain Chroma
- ChromaDB
- OpenAI API
- OpenAI embeddings
- Roboflow hosted inference
- OpenCV
- Pillow
- Pytest
- OpenWeather API
- TomTom Traffic API
- Ticketmaster Discovery API
- HTML/CSS/JavaScript frontend

## Resume-Friendly Description

Built an end-to-end multi-agent AI system for bridge infrastructure inspection, defect analysis, maintenance planning, and repair scheduling. The system combines computer vision, RAG, live operational APIs, and LLM-assisted reasoning to convert inspection evidence into a formal maintenance report. Implemented a LangGraph agent workflow, LangChain/Chroma persistent RAG with OpenAI embeddings, Roboflow-based defect detection, OpenCV video frame extraction, live weather/traffic/event scheduling context, and a FastAPI demo UI with drag-and-drop image upload and PDF-style report export. Added comprehensive offline tests and dataset evaluations to validate vision, retrieval, scheduling, and report generation behavior.

## Resume Bullet Options

- Built a multi-agent infrastructure inspection system using LangGraph, FastAPI, LangChain, ChromaDB, OpenAI, and Roboflow to automate defect detection, severity assessment, maintenance planning, repair scheduling, and report generation.
- Implemented a persistent hierarchical RAG pipeline with LangChain Chroma, OpenAI embeddings, metadata filtering, parent/child chunking, semantic chunk merging, and retrieval over standards, manuals, repair histories, and scheduling precedents.
- Integrated Roboflow bridge defect detection and optional OpenAI vision verification to analyze real bridge images and generate structured defect observations with confidence scores and bounding boxes.
- Developed a hybrid Scheduling Agent that combines RAG scheduling precedents, deterministic scoring, LLM-assisted selection, and live OpenWeather, TomTom Traffic, and Ticketmaster event context to minimize repair disruption.
- Created a FastAPI-backed testing and presentation UI with drag-and-drop image upload, live/mock mode controls, RAG traceability panels, maintenance plan summaries, and formal report export.
- Built an evaluation and test suite covering pipeline behavior, RAG retrieval quality, detector performance, scheduling decisions, API behavior, upload handling, and graph-level workflow correctness.

## Current Status

The project is paused at a demo-ready prototype stage. The main technical flow is complete:

- Evidence intake works.
- Image upload works.
- Vision analysis works.
- RAG retrieval works.
- Severity and maintenance planning work.
- Live scheduling context works.
- Formal report preview and export work.
- Automated tests are passing.

Recommended future work:

- Add persistent case history under `artifacts/cases`.
- Surface annotated detection images directly in the UI.
- Add human review/edit controls for severity, defect label, schedule, and report text.
- Add server-side PDF generation for stable report exports.
- Run a final end-to-end benchmark using real bridge images and live context.
