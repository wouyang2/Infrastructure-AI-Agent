from __future__ import annotations

from argparse import Namespace

from evals.rag_retrieval_eval import run_rag_retrieval_eval


def test_rag_retrieval_eval_scores_bridge_corpus_with_fake_embeddings(tmp_path) -> None:
    output_json = tmp_path / "rag_eval.json"
    output_md = tmp_path / "rag_eval.md"

    result = run_rag_retrieval_eval(
        Namespace(
            output_json=str(output_json),
            output_md=str(output_md),
            knowledge_corpus="bridge",
            rag_backend="chroma",
            embedding_backend="fake",
            embedding_model=None,
            chroma_persist_dir=str(tmp_path / "chroma"),
            rebuild_rag_index=True,
            limit=3,
        )
    )

    assert result["case_count"] == 6
    assert result["metrics"]["top_k_hit_rate"] == 1.0
    assert result["metrics"]["wrong_defect_retrieval_rate"] == 0.0
    assert output_json.exists()
    assert output_md.exists()


def test_rag_retrieval_eval_reports_source_type_breakdowns(tmp_path) -> None:
    result = run_rag_retrieval_eval(
        Namespace(
            output_json=str(tmp_path / "rag_eval.json"),
            output_md=str(tmp_path / "rag_eval.md"),
            knowledge_corpus="bridge",
            rag_backend="chroma",
            embedding_backend="fake",
            embedding_model=None,
            chroma_persist_dir=str(tmp_path / "chroma"),
            rebuild_rag_index=True,
            limit=3,
        )
    )

    by_source = result["metrics_by_source_type"]

    assert by_source["standard"]["case_count"] == 3
    assert by_source["repair_record"]["case_count"] == 2
    assert by_source["schedule_record"]["case_count"] == 1
