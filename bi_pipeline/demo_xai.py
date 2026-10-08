from __future__ import annotations

import json
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import pandas as pd
from bi_pipeline.agents.bi_analyst_agent import BIAnalystAgent
from bi_pipeline.agents.semantic_kpi_agent import BISemanticKPIAgent


def run_xai_demonstration():
    print("=" * 75)
    print("       DEMONSTRATION XAI (EXPLAINABLE AI) & AUDIT LINEAGE")
    print("=" * 75)

    # 1. Load data
    data_path = BASE_DIR / "bi_pipeline" / "data" / "mock_clean_data.csv"
    df = pd.read_csv(data_path)
    print(f"\n[1] DONNEES CHARGEES : {len(df)} lignes brutes transactionnelles")

    # 2. Agent 5 computes numbers with full lineage
    agent5 = BISemanticKPIAgent()
    sem_state = agent5.analyze(df, dataset_name="Superstore Retail", domain_hint="retail orders")

    # 3. Agent 6 derives statistics with threshold lineage
    agent6 = BIAnalystAgent()
    analyst_state = agent6.analyze(sem_state)

    # 4. Display XAI KPI Lineage
    target_kpi = sem_state.kpis[0]  # Total Revenue
    print("\n[2] PREUVE XAI D'UN CHIFFRE COMPTABLE (Agent 5 - DuckDB Engine) :")
    print("-" * 75)
    print(f"  * KPI calcule               : {target_kpi.name} = {target_kpi.value} {target_kpi.unit}")
    print(f"  * Document RAG source       : {target_kpi.lineage.source_document}")
    print(f"  * Tier RAG applique         : {target_kpi.lineage.tier} (Confiance: {target_kpi.lineage.similarity_score * 100:.1f}%)")
    print(f"  * Colonnes DataFrame        : {target_kpi.lineage.input_columns_used}")
    print(f"  * REQUETE SQL EXACTE DUCKDB :")
    print(f"    --> {target_kpi.lineage.exact_sql_query}")
    print(f"  * Horodatage UTC certifie   : {target_kpi.lineage.execution_timestamp}")

    # 5. Display XAI Anomaly Lineage
    anomaly = next((a for a in analyst_state.statistical_anomalies if a.observed_value < 0), analyst_state.statistical_anomalies[0])
    print("\n[3] PREUVE XAI D'UNE ANOMALIE STATISTIQUE (Agent 6 - Statistical Mining) :")
    print("-" * 75)
    print(f"  * Anomalie detectee         : {anomaly.entity} ({anomaly.metric_name})")
    print(f"  * Severite du risque        : {anomaly.severity.value.upper()}")
    print(f"  * Valeur observee           : {anomaly.observed_value:,.2f} $")
    print(f"  * Baseline (Moyenne attendue): {anomaly.expected_value:,.2f} $")
    print(f"  * Z-Score calcule           : {anomaly.z_score} ecarts-types")
    print(f"  * Deviation relative        : {anomaly.pct_deviation:+.1f} %")
    print(f"  * Regle de decision XAI     : {anomaly.lineage.exact_sql_query.strip()}")
    print(f"  * Seuils statistiques       : {json.dumps(anomaly.lineage.statistical_thresholds)}")

    # 6. JSON Export for Downstream XAI / Auditor Agent
    print("\n[4] PAYLOAD JSON BRUT TRANSMIS A L'AGENT AUDITEUR (Contrat Pydantic V2) :")
    print("-" * 75)
    sample_payload = {
        "kpi_name": target_kpi.name,
        "kpi_value": target_kpi.value,
        "lineage": target_kpi.lineage.model_dump(mode="json"),
        "anomaly_sample": anomaly.model_dump(mode="json"),
    }
    print(json.dumps(sample_payload, indent=2))
    print("=" * 75)
    print("   CONCLUSION XAI : ZERO BOITE NOIRE. 100% AUDITABLE ET MATHEMATIQUEMENT PROUVABLE.")
    print("=" * 75)


if __name__ == "__main__":
    run_xai_demonstration()
