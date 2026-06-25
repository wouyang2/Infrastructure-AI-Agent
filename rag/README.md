# RAG Layer Guide

This folder owns retrieval-augmented generation support for the inspection agents.
The goal is to let agents ask: "What standards or historical repair records are relevant to this inspection?"

## How The Pieces Fit Together

```text
workflow / agent
  -> build_retriever(...)
  -> selected retriever
  -> search(...)
  -> Citation objects
  -> severity / maintenance / report
```

The agents do not need to know whether retrieval is lexical, Chroma, fake embeddings, or OpenAI embeddings.
They only depend on the shared `KnowledgeRetriever` shape.

## Files

### `interfaces.py`

Defines the shared retriever contract:

- `search(...) -> list[Citation]`
- `get_document(document_id) -> dict | None`

Anything that implements these methods can be used by the agents.

### `retriever_factory.py`

Builds the retriever used by the workflow.

Current options:

- `rag_backend="chroma"`: use LangChain Chroma vector search.
- `rag_backend="local"`: use the simple lexical fallback.
- `embedding_backend="fake"`: deterministic offline embeddings.
- `embedding_backend="openai"`: OpenAI embeddings through `langchain_openai`.

The default is:

```python
build_retriever(documents, rag_backend="chroma", embedding_backend="openai")
```

### `data/knowledge_corpus.py`

Builds normalized document records before they enter the retriever.

Current corpus modes:

- `sample`: tiny stable records from `data/sample_knowledge.py`.
- `bridge`: generated bridge standards, manuals, inspection reports, and repair records from `data/bridge_knowledge/`.
- `merged`: sample records plus bridge records, with duplicate document IDs removed.

### `langchain_chroma_retriever.py`

This is the default RAG backend.

Responsibilities:

- Split normalized knowledge records into parent chunks and overlapping child chunks.
- Put child chunks into a persistent Chroma vector store.
- Run vector search.
- Merge semantically similar sibling child chunks into citation excerpts.
- Filter by metadata such as `source_type`, `asset_type`, and `defect_type`.
- Convert retrieved LangChain documents back into our app's `Citation` objects.

This file is the main place to edit when we add:

- richer metadata filters
- document loaders

### `fake_embeddings.py`

Provides `DeterministicFakeEmbeddings`.

This is not a real semantic embedding model. It turns words into stable numeric vectors using hashing.
That means tests can run offline and return repeatable results.

Use this for development and tests.
Use OpenAI embeddings for the normal runtime.

### `retriever.py`

Contains `LocalRetriever`, the old lexical fallback.

It does keyword-style matching over document text and metadata.
Keep it for debugging and offline fallback, but the default workflow should use Chroma.

## Where The Data Comes From

The workflow seeds the knowledge base through:

```text
data/knowledge_corpus.py
```

Each record has fields like:

- `document_id`
- `title`
- `source_type`
- `asset_type`
- `defect_type`
- `severity`
- `repair_method`
- `content`

The bridge corpus currently reads:

- `data/bridge_knowledge/standards.jsonl`
- `data/bridge_knowledge/manuals.jsonl`
- `data/bridge_knowledge/inspection_reports.jsonl`
- `data/bridge_knowledge/repair_records.csv`

The Chroma retriever converts each record into child chunks like:

```python
Document(
    page_content=child_chunk.text,
    metadata={... document_id, parent_id, child_id, chunk_index ...}
)
```

## Example Retrieval Calls

Severity agent asks for policy/standard context:

```python
retriever.search(
    "bridge spalling loose concrete exposed substrate",
    source_type="standard",
    asset_type="bridge",
    defect_type="spalling",
)
```

Maintenance planning agent asks for historical repair precedents:

```python
retriever.search(
    "bridge spalling partial closure concrete patch",
    source_type="repair_record",
    asset_type="bridge",
    defect_type="spalling",
)
```

## CLI Usage

OpenAI-backed default:

```bash
python3 main.py --rag-backend chroma --embedding-backend openai --knowledge-corpus merged
```

Offline/test mode:

```bash
python3 main.py --rag-backend chroma --embedding-backend fake --knowledge-corpus merged
```

Bridge-only corpus:

```bash
python3 main.py --knowledge-corpus bridge
```

Lexical fallback:

```bash
python3 main.py --rag-backend local
```

Real OpenAI embeddings:

```bash
python3 main.py --rag-backend chroma --embedding-backend openai --embedding-model text-embedding-3-small
```

OpenAI embeddings require `OPENAI_API_KEY` in `.env` or your shell environment.

Persistent Chroma defaults to `artifacts/chroma`:

```bash
python3 main.py --chroma-persist-dir artifacts/chroma --rebuild-rag-index
```

Bridge dataset eval:

```bash
python3 -m evals.bridge_dataset_eval
```

Image-inference eval against the same labels:

```bash
python3 -m evals.bridge_dataset_eval --image-analyzer openai
```

## Current Design Choice

RAG is a service/tool, not a separate decision-making agent.

The domain agents retrieve knowledge when they need it:

- Severity Agent retrieves standards.
- Maintenance Planning Agent retrieves repair history.
- Scheduling Agent can later retrieve disruption and access history.

This keeps judgment inside the domain agents and keeps retrieval auditable.
