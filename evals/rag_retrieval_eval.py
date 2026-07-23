from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from data.knowledge_corpus import load_knowledge_documents
from rag.retriever_factory import build_retriever


DEFECT_TERMS = {
    "crack": ("crack", "cracking"),
    "spalling": ("spalling", "spall"),
    "exposed_rebar": (
        "exposed_rebar",
        "exposed rebar",
        "exposed reinforcement",
        "reinforcement",
        "rebar",
    ),
    "corrosion": ("corrosion", "corroded", "rust"),
    "leak": ("leak", "water leak", "seepage", "efflorescence"),
    "water_leak": ("leak", "water leak", "seepage", "efflorescence"),
}


@dataclass(frozen=True)
class RetrievalEvalCase:
    case_id: str
    query: str
    source_type: str
    asset_type: str
    defect_type: str
    expected_document_ids: tuple[str, ...]
    description: str


DEFAULT_CASES = [
    RetrievalEvalCase(
        case_id="RAG-STD-SPALLING",
        query="bridge spalling loose concrete missing cover exposed substrate",
        source_type="standard",
        asset_type="bridge",
        defect_type="spalling",
        expected_document_ids=("STD-BRIDGE-SPALLING-001",),
        description="Bridge spalling should retrieve the spalling standard.",
    ),
    RetrievalEvalCase(
        case_id="RAG-STD-REBAR",
        query="bridge exposed rebar exposed reinforcement corrosion risk",
        source_type="standard",
        asset_type="bridge",
        defect_type="exposed_rebar",
        expected_document_ids=("STD-BRIDGE-REBAR-001",),
        description="Exposed reinforcement should retrieve the rebar standard.",
    ),
    RetrievalEvalCase(
        case_id="RAG-STD-LEAK",
        query="bridge leak water seepage drainage staining efflorescence",
        source_type="standard",
        asset_type="bridge",
        defect_type="leak",
        expected_document_ids=("STD-BRIDGE-LEAK-001",),
        description="Leak aliases should retrieve water-leak guidance.",
    ),
    RetrievalEvalCase(
        case_id="RAG-REPAIR-SPALLING",
        query="bridge spalling partial-depth concrete patch repair history",
        source_type="repair_record",
        asset_type="bridge",
        defect_type="spalling",
        expected_document_ids=("HIST-BRIDGE-",),
        description="Spalling repair queries should retrieve bridge repair precedents.",
    ),
    RetrievalEvalCase(
        case_id="RAG-REPAIR-CRACK",
        query="bridge crack routing sealing flexible sealant repair record",
        source_type="repair_record",
        asset_type="bridge",
        defect_type="crack",
        expected_document_ids=("HIST-BRIDGE-",),
        description="Crack repair queries should retrieve bridge crack repair records.",
    ),
    RetrievalEvalCase(
        case_id="RAG-SCHEDULE-SPALLING",
        query=(
            "bridge spalling concrete patch scheduling closure weather traffic "
            "crew access disruption"
        ),
        source_type="schedule_record",
        asset_type="bridge",
        defect_type="spalling",
        expected_document_ids=("SCHED-BRIDGE-",),
        description="Spalling scheduling queries should retrieve scheduling precedents.",
    ),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate RAG retrieval quality against expected document IDs."
    )
    parser.add_argument("--output-json", default="artifacts/evals/rag_retrieval_eval.json")
    parser.add_argument("--output-md", default="artifacts/evals/rag_retrieval_eval.md")
    parser.add_argument("--knowledge-corpus", choices=["sample", "bridge", "merged"], default="bridge")
    parser.add_argument("--rag-backend", choices=["chroma", "local"], default="chroma")
    parser.add_argument("--embedding-backend", choices=["fake", "openai"], default="fake")
    parser.add_argument("--embedding-model", default=None)
    parser.add_argument("--chroma-persist-dir", default="artifacts/chroma")
    parser.add_argument("--rebuild-rag-index", action="store_true")
    parser.add_argument("--limit", type=int, default=3)
    return parser


def run_rag_retrieval_eval(args: argparse.Namespace) -> dict[str, Any]:
    documents = load_knowledge_documents(args.knowledge_corpus)
    retriever = build_retriever(
        documents,
        rag_backend=args.rag_backend,
        embedding_backend=args.embedding_backend,
        embedding_model=args.embedding_model,
        persist_directory=args.chroma_persist_dir,
        rebuild_index=args.rebuild_rag_index,
    )

    cases = [_score_case(retriever, case, limit=args.limit) for case in DEFAULT_CASES]
    result = {
        "knowledge_corpus": args.knowledge_corpus,
        "rag_backend": args.rag_backend,
        "embedding_backend": args.embedding_backend,
        "embedding_model": args.embedding_model,
        "limit": args.limit,
        "case_count": len(cases),
        "metrics": _metrics(cases),
        "metrics_by_source_type": _metrics_by_group(cases, "source_type"),
        "metrics_by_defect_type": _metrics_by_group(cases, "defect_type"),
        "cases": cases,
    }
    _write_json(Path(args.output_json), result)
    _write_markdown(Path(args.output_md), result)
    return result


def _score_case(retriever, case: RetrievalEvalCase, *, limit: int) -> dict[str, Any]:
    started = time.perf_counter()
    citations = retriever.search(
        case.query,
        source_type=case.source_type,
        asset_type=case.asset_type,
        defect_type=case.defect_type,
        limit=limit,
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    retrieved_ids = [citation.document_id for citation in citations]
    hit_positions = [
        index + 1
        for index, document_id in enumerate(retrieved_ids)
        if _matches_expected(document_id, case.expected_document_ids)
    ]
    top_1_hit = bool(hit_positions and hit_positions[0] == 1)
    top_k_hit = bool(hit_positions)
    wrong_defect_ids = [
        citation.document_id
        for citation in citations
        if not _text_matches_defect(
            f"{citation.document_id} {citation.title} {citation.excerpt}",
            case.defect_type,
        )
    ]
    return {
        **asdict(case),
        "expected_document_ids": list(case.expected_document_ids),
        "retrieved_document_ids": retrieved_ids,
        "retrieved_citations": [
            {
                "document_id": citation.document_id,
                "title": citation.title,
                "source_type": citation.source_type,
                "score": citation.score,
                "excerpt_preview": citation.excerpt[:240],
            }
            for citation in citations
        ],
        "top_1_hit": top_1_hit,
        "top_k_hit": top_k_hit,
        "first_hit_rank": hit_positions[0] if hit_positions else None,
        "wrong_defect_ids": wrong_defect_ids,
        "latency_ms": latency_ms,
    }


def _matches_expected(document_id: str, expected_document_ids: tuple[str, ...]) -> bool:
    return any(
        document_id == expected or document_id.startswith(expected)
        for expected in expected_document_ids
    )


def _text_matches_defect(text: str, defect_type: str) -> bool:
    normalized = text.lower().replace("-", " ")
    terms = DEFECT_TERMS.get(
        defect_type,
        (defect_type, defect_type.replace("_", " ")),
    )
    return any(term in normalized for term in terms)


def _metrics(cases: list[dict[str, Any]]) -> dict[str, float]:
    if not cases:
        return {
            "top_1_accuracy": 0.0,
            "top_k_hit_rate": 0.0,
            "wrong_defect_retrieval_rate": 0.0,
            "average_retrieved_citations_per_case": 0.0,
            "average_latency_ms": 0.0,
            "p50_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "p99_latency_ms": 0.0,
        }
    latencies = sorted(float(case["latency_ms"]) for case in cases)
    return {
        "top_1_accuracy": _rate(cases, "top_1_hit"),
        "top_k_hit_rate": _rate(cases, "top_k_hit"),
        "wrong_defect_retrieval_rate": round(
            sum(1 for case in cases if case["wrong_defect_ids"]) / len(cases),
            3,
        ),
        "average_retrieved_citations_per_case": round(
            sum(len(case["retrieved_document_ids"]) for case in cases) / len(cases),
            3,
        ),
        "average_latency_ms": round(sum(latencies) / len(latencies), 3),
        "p50_latency_ms": _percentile(latencies, 50),
        "p95_latency_ms": _percentile(latencies, 95),
        "p99_latency_ms": _percentile(latencies, 99),
    }


def _metrics_by_group(
    cases: list[dict[str, Any]],
    field: str,
) -> dict[str, dict[str, float | int]]:
    groups = sorted({str(case[field]) for case in cases})
    return {
        group: {
            "case_count": len(group_cases),
            **_metrics(group_cases),
        }
        for group in groups
        for group_cases in [[case for case in cases if str(case[field]) == group]]
    }


def _rate(cases: list[dict[str, Any]], field: str) -> float:
    if not cases:
        return 0.0
    return round(sum(1 for case in cases if case[field]) / len(cases), 3)


def _percentile(sorted_values: list[float], percentile: int) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return round(sorted_values[0], 3)
    rank = (percentile / 100) * (len(sorted_values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower
    value = sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight
    return round(value, 3)


def _write_json(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")


def _write_markdown(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metrics = result["metrics"]
    lines = [
        "# RAG Retrieval Eval",
        "",
        f"Knowledge corpus: {result['knowledge_corpus']}",
        f"RAG backend: {result['rag_backend']}",
        f"Embedding backend: {result['embedding_backend']}",
        f"Embedding model: {result['embedding_model'] or 'default'}",
        f"Top-k limit: {result['limit']}",
        f"Cases: {result['case_count']}",
        "",
        "## Metrics",
        "",
    ]
    for key, value in metrics.items():
        lines.append(f"- {key}: {value}")

    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| Case | Source | Defect | Top-1 | Top-k | First Hit | Latency ms | Retrieved IDs |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for case in result["cases"]:
        lines.append(
            f"| {case['case_id']} | {case['source_type']} | {case['defect_type']} | "
            f"{case['top_1_hit']} | {case['top_k_hit']} | "
            f"{case['first_hit_rank'] or 'n/a'} | {case['latency_ms']} | "
            f"{', '.join(case['retrieved_document_ids']) or 'none'} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    result = run_rag_retrieval_eval(build_parser().parse_args())
    print(json.dumps({"case_count": result["case_count"], "metrics": result["metrics"]}, indent=2))


if __name__ == "__main__":
    main()
