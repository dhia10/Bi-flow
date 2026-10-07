from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import pytest

PIPELINE_ROOT = Path(__file__).resolve().parent
if str(PIPELINE_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT.parent))

from bi_pipeline.agents.bi_analyst_agent import BIAnalystAgent
from bi_pipeline.agents.rag_engine import DomainRAGEngine
from bi_pipeline.agents.semantic_kpi_agent import BISemanticKPIAgent
from bi_pipeline.schemas.state_schema import (
    AuditLineage,
    BIAnalystState,
    PipelineRunOutput,
    SemanticKPIState,
)


def _load_retail_csv() -> pd.DataFrame:
    p = PIPELINE_ROOT / "data" / "mock_clean_data.csv"
    df = pd.read_csv(p)
    df["order_date"] = pd.to_datetime(df["order_date"])
    return df


def _make_iot_sample() -> pd.DataFrame:
    return pd.DataFrame({
        "machine_id": [f"CNC-{i % 5 + 101}" for i in range(50)],
        "timestamp": pd.date_range("2024-01-01", periods=50, freq="D").strftime("%Y-%m-%d"),
        "temperature_celsius": [65.0 + (i % 15) * 1.8 + (12.0 if i == 27 else 0) for i in range(50)],
        "vibration_frequency_hz": [120.0 + (i % 8) * 3.5 for i in range(50)],
        "facility_zone": [f"Sector-{['Alpha', 'Beta', 'Gamma'][i % 3]}" for i in range(50)],
        "cycle_count": [1000 + i * 25 for i in range(50)],
    })


def test_tier_1_retail():
    df = _load_retail_csv()
    agent5 = BISemanticKPIAgent(DomainRAGEngine(similarity_threshold=0.30))
    agent6 = BIAnalystAgent()

    sem = agent5.analyze(df, dataset_name="superstore_sales", domain_hint="retail store sales")
    assert sem.rag_tier == "tier_1_verified_rag"
    assert sem.inferred_domain == "retail_ecommerce"
    assert sem.domain_confidence >= 0.30

    rev_kpi = next((k for k in sem.kpis if k.kpi_id == "kpi_total_revenue"), None)
    assert rev_kpi is not None
    assert isinstance(rev_kpi.value, (int, float)) and rev_kpi.value > 0
    assert rev_kpi.lineage.tier == "tier_1_verified_rag"
    assert "SELECT" in rev_kpi.lineage.exact_sql_query.upper()

    ana = agent6.analyze(sem)
    assert isinstance(ana, BIAnalystState)
    assert len(ana.strategic_takeaways) > 0
    assert len(ana.executive_narrative) > 100

    for a in ana.statistical_anomalies:
        assert isinstance(a.lineage, AuditLineage)
    for t in ana.strategic_takeaways:
        assert len(t.recommended_action) > 0


def test_tier_2_unseen_domain():
    df = _make_iot_sample()
    agent5 = BISemanticKPIAgent(DomainRAGEngine(similarity_threshold=0.30))
    agent6 = BIAnalystAgent()

    sem = agent5.analyze(df, dataset_name="factory_telemetry")
    assert sem.rag_tier == "tier_2_zero_shot_induction"
    assert sem.inferred_domain == "unseen_domain_universal"

    vol_kpi = next((k for k in sem.kpis if k.kpi_id == "tier2_total_volume"), None)
    assert vol_kpi is not None
    assert vol_kpi.value == len(df)
    assert vol_kpi.lineage.tier == "tier_2_zero_shot_induction"

    ana = agent6.analyze(sem)
    assert len(ana.strategic_takeaways) > 0


def test_pydantic_serialization():
    df = _load_retail_csv()
    sem = BISemanticKPIAgent().analyze(df, "serialize_test")
    ana = BIAnalystAgent().analyze(sem)

    out = PipelineRunOutput(
        semantic_state=sem,
        analyst_state=ana,
        total_execution_time_ms=sem.execution_time_ms + 10.0,
    )
    raw_json = out.to_json()
    assert isinstance(raw_json, str) and len(raw_json) > 0

    restored = PipelineRunOutput.model_validate_json(raw_json)
    assert restored.semantic_state.dataset_name == "serialize_test"
    assert len(restored.semantic_state.kpis) == len(sem.kpis)
    assert len(restored.analyst_state.strategic_takeaways) == len(ana.strategic_takeaways)


def test_olist_order_items_dataset():
    p = PIPELINE_ROOT.parent / "olist_order_items_dataset.csv"
    if not p.is_file():
        pytest.skip(f"Olist dataset not present at {p}")

    df = pd.read_csv(p, nrows=5000)
    agent5 = BISemanticKPIAgent(DomainRAGEngine(similarity_threshold=0.25))
    agent6 = BIAnalystAgent()

    sem = agent5.analyze(df, dataset_name="olist_order_items", domain_hint="ecommerce orders")
    assert sem.row_count == len(df)
    assert len(sem.kpis) > 0
    assert sem.execution_time_ms < 500.0

    ana = agent6.analyze(sem)
    assert ana.dataset_name == "olist_order_items"
    assert len(ana.executive_narrative) > 50


def test_olist_order_payments_dataset():
    p = PIPELINE_ROOT.parent / "olist_order_payments_dataset.csv"
    if not p.is_file():
        pytest.skip(f"Olist payments dataset not present at {p}")

    df = pd.read_csv(p, nrows=5000)
    agent5 = BISemanticKPIAgent(DomainRAGEngine(similarity_threshold=0.25))
    agent6 = BIAnalystAgent()

    sem = agent5.analyze(df, dataset_name="olist_order_payments", domain_hint="payments commerce")
    assert sem.row_count == len(df)
    assert len(sem.kpis) > 0

    ana = agent6.analyze(sem)
    assert len(ana.strategic_takeaways) > 0


def test_olist_geolocation_tier2_fallback():
    p = PIPELINE_ROOT.parent / "olist_geolocation_dataset.csv"
    if not p.is_file():
        pytest.skip(f"Olist geolocation dataset not present at {p}")

    df = pd.read_csv(p, nrows=1000)
    agent5 = BISemanticKPIAgent(DomainRAGEngine(similarity_threshold=0.30))
    agent6 = BIAnalystAgent()

    sem = agent5.analyze(df, dataset_name="olist_geolocation")
    assert sem.rag_tier == "tier_2_zero_shot_induction"
    assert len(sem.kpis) > 0

    ana = agent6.analyze(sem)
    assert ana is not None
