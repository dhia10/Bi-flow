from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src.api.routes import app
from src.cache.semantic_cache import SemanticCache
from src.eval.rag_metrics import RAGMetricEvaluator
from src.generation.grounded_answer import GroundedAnswerGenerator
from src.ingestion.indexer import KnowledgeIndexer
from src.pipelines.query_pipeline import ProductionQueryPipeline
from src.rerank.reranker import SemanticReranker
from src.retrieval.retriever import HybridRetriever
from src.schemas.models import (
    AnomalyReport,
    DuckDBExecutionProof,
    OntologyChunk,
    RAGASEvalMetrics,
    RiskSeverity,
    SemanticMappingResult,
    XAIResponsePayload,
)


@pytest.fixture
def mock_df() -> pd.DataFrame:
    csv_path = ROOT_DIR / "bi_pipeline" / "data" / "mock_clean_data.csv"
    return pd.read_csv(csv_path)


def test_pydantic_v2_models():
    chunk = OntologyChunk(
        chunk_id="test_chunk",
        domain="retail_ecommerce",
        entity_type="kpi",
        name="Test KPI",
        content="Test content",
        sql_template="SELECT 1",
    )
    assert chunk.chunk_id == "test_chunk"

    proof = DuckDBExecutionProof(
        kpi_id="kpi_1",
        kpi_name="Total Revenue",
        value=1500.5,
        exact_sql="SELECT SUM(sales) FROM df",
        latency_ms=1.5,
        source_chunk_id="test_chunk",
    )
    assert proof.value == 1500.5

    anomaly = AnomalyReport(
        dimension="category",
        entity="Furniture",
        metric="profit",
        observed_value=-150.0,
        baseline_value=300.0,
        deviation_pct=-150.0,
        severity=RiskSeverity.CRITICAL,
        proof_rule="-- Negative profit",
        description="Operating at loss",
    )
    assert anomaly.severity == RiskSeverity.CRITICAL


def test_hybrid_search_and_reranking(mock_df):
    kb_dir = ROOT_DIR / "bi_pipeline" / "knowledge_base"
    indexer = KnowledgeIndexer(kb_dir=kb_dir)
    retriever = HybridRetriever(indexer=indexer)
    reranker = SemanticReranker(target_threshold=0.85)

    candidates = retriever.retrieve("retail sales revenue orders", top_k=5)
    assert len(candidates) > 0

    reranked = reranker.rerank(
        query="sales revenue",
        candidates=candidates,
        available_columns=list(mock_df.columns),
        top_k=3,
    )
    assert len(reranked) > 0
    top_score = reranked[0][1]
    assert top_score >= 0.85, f"Reranker failed to calibrate score above 0.85: got {top_score}"


def test_grounded_answer_and_abstention():
    grounder = GroundedAnswerGenerator(min_confidence_threshold=0.40)

    # 1. Normal confident case
    dummy_chunk = OntologyChunk(
        chunk_id="chunk_kpi_sales",
        domain="retail",
        entity_type="kpi",
        name="Total Sales",
        content="Total Sales content",
    )
    proof = DuckDBExecutionProof(
        kpi_id="kpi_sales",
        kpi_name="Total Sales",
        value=5000.0,
        exact_sql="SELECT SUM(sales) FROM df",
        latency_ms=2.0,
        source_chunk_id="chunk_kpi_sales",
    )
    narrative, citations, was_abstained = grounder.generate(
        dataset_name="Test Store",
        detected_domain="retail",
        retrieval_confidence=0.95,
        retrieved_chunks=[(dummy_chunk, 0.95)],
        duckdb_proofs=[proof],
        raw_summary="Chiffre d'affaires conforme.",
    )
    assert not was_abstained
    assert len(citations) > 0
    assert "chunk_kpi_sales" in citations[0]

    # 2. Low confidence abstention policy
    narrative_low, _, was_abstained_low = grounder.generate(
        dataset_name="Unknown Store",
        detected_domain="unknown",
        retrieval_confidence=0.15,
        retrieved_chunks=[],
        duckdb_proofs=[],
        raw_summary="Some raw guess.",
    )
    assert was_abstained_low
    assert "ABSTENTION STRICTE" in narrative_low


def test_ragas_evaluation_metrics():
    evaluator = RAGMetricEvaluator()
    dummy_chunk = OntologyChunk(
        chunk_id="chunk_kpi_sales",
        domain="retail",
        entity_type="kpi",
        name="Total Sales",
        content="Total Sales content",
    )
    proof = DuckDBExecutionProof(
        kpi_id="kpi_sales",
        kpi_name="Total Sales",
        value=28424.33,
        exact_sql="SELECT SUM(sales) FROM df",
        latency_ms=2.0,
        source_chunk_id="chunk_kpi_sales",
    )
    metrics = evaluator.evaluate(
        retrieved_chunks=[dummy_chunk],
        target_concepts=["sales_amount"],
        duckdb_proofs=[proof],
        executive_narrative="Chiffre d'affaires certifie de 28,424.33 $ sans anomalie.",
    )
    assert isinstance(metrics, RAGASEvalMetrics)
    assert metrics.faithfulness == 1.0
    assert metrics.sql_exact_match == 1.0


def test_end_to_end_production_pipeline(mock_df):
    pipeline = ProductionQueryPipeline()
    payload = pipeline.run(mock_df, dataset_name="Test Store")
    assert isinstance(payload, XAIResponsePayload)
    assert payload.retrieval_relevance_score >= 0.85
    assert len(payload.duckdb_proofs) > 0
    assert payload.eval_metrics.faithfulness == 1.0
    assert payload.eval_metrics.sql_exact_match == 1.0


def test_fastapi_decoupled_microservices():
    client = TestClient(app)

    # 1. Ingest
    res1 = client.post("/api/v1/ingest", json={"force_rebuild": False})
    assert res1.status_code == 200
    assert res1.json()["status"] == "success"

    # 2. Agent 5 Map & Query
    res2 = client.post("/api/v1/agent5/map-and-query", json={"dataset_name": "Test Superstore"})
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["retrieval_relevance_score"] >= 0.85
    assert len(data2["semantic_mappings"]) > 0
    assert len(data2["duckdb_proofs"]) > 0

    # 3. Agent 6 Detect Anomalies
    res3 = client.post("/api/v1/agent6/detect-anomalies", json={"z_threshold": 2.0})
    assert res3.status_code == 200
    data3 = res3.json()
    assert "has_critical_risk" in data3

    # 4. Agent 6 COMEX Synthesis
    res4 = client.post(
        "/api/v1/agent6/comex-synthesis",
        json={
            "dataset_name": data2["dataset_name"],
            "detected_domain": data2["detected_domain"],
            "retrieval_confidence": data2["retrieval_relevance_score"],
            "duckdb_proofs": data2["duckdb_proofs"],
            "statistical_anomalies": data3["anomalies"],
        },
    )
    assert res4.status_code == 200
    data4 = res4.json()
    assert len(data4["executive_narrative"]) > 0
    assert data4["eval_metrics"]["faithfulness"] == 1.0
