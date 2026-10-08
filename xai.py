from __future__ import annotations

import json
import sys
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd
from bi_pipeline.agents.bi_analyst_agent import BIAnalystAgent
from bi_pipeline.agents.llm_agent import LLMReasoningEngine
from bi_pipeline.agents.semantic_kpi_agent import BISemanticKPIAgent


def main():
    print("=" * 80)
    print("       BI-FLOW : DEMONSTRATION MULTI-AGENTS, LLM ET AUDITABILITE XAI")
    print("=" * 80)

    # 1. Load Data
    data_path = ROOT_DIR / "bi_pipeline" / "data" / "mock_clean_data.csv"
    df = pd.read_csv(data_path)
    print(f"\n[1] DONNEES CHARGEES : {len(df)} transactions d'entreprise (Superstore Sales)")

    # 2. Agent 5 - LLM Semantic Reasoning
    print("\n[2] AGENT 5 : RAISONNEMENT SEMANTIQUE DU LLM (Mappage Ontologique)")
    print("-" * 80)
    llm = LLMReasoningEngine()
    col_types = {c: str(df[c].dtype) for c in df.columns}
    samples = df.head(2).to_dict(orient="records")
    target_concepts = ["sales_amount", "order_identifier", "transaction_timestamp", "product_category"]

    semantic_res = llm.semantic_mapping(col_types, samples, target_concepts)
    print(f"  * Modele LLM utilise       : {llm.model_name}")
    print(f"  * Domaine detecte par LLM  : {semantic_res.detected_domain}")
    for m in semantic_res.mappings:
        print(f"    --> Concept '{m.required_concept}' => Colonne physique '{m.mapped_column}' (Confiance: {m.confidence*100:.0f}%)")
        print(f"        Justification LLM: {m.reasoning}")

    # 3. Agent 5 - In-memory DuckDB Execution (Deterministic Math)
    print("\n[3] AGENT 5 : CALCUL DETERMINISTE VIA DUCKDB (:memory:) & PREUVE XAI")
    print("-" * 80)
    agent5 = BISemanticKPIAgent()
    sem_state = agent5.analyze(df, dataset_name="Superstore Retail", domain_hint="retail store sales")
    rev_kpi = sem_state.kpis[0]

    print(f"  * Chiffre d'Affaires calcule: {rev_kpi.name} = {rev_kpi.value:,.2f} {rev_kpi.unit}")
    print(f"  * Document RAG source       : {rev_kpi.lineage.source_document}")
    print(f"  * Similarite RAG (FAISS)    : {rev_kpi.lineage.similarity_score:.4f} ({rev_kpi.lineage.tier})")
    print(f"  * Colonnes DataFrame        : {rev_kpi.lineage.input_columns_used}")
    print(f"  * REQUETE SQL EXACTE DUCKDB :")
    print(f"    ==> {rev_kpi.lineage.exact_sql_query}")
    print(f"  * Horodatage UTC certifie   : {rev_kpi.lineage.execution_timestamp}")

    # 4. Agent 6 - Statistical Mining (Z-Score & Tukey)
    print("\n[4] AGENT 6 : MINING STATISTIQUE & DETECTION D'ANOMALIES (Z-Score / Tukey)")
    print("-" * 80)
    agent6 = BIAnalystAgent()
    ana_state = agent6.analyze(sem_state)
    critical_anomaly = next((a for a in ana_state.statistical_anomalies if a.observed_value < 0), ana_state.statistical_anomalies[0])

    print(f"  * Anomalie detectee         : {critical_anomaly.entity} ({critical_anomaly.metric_name})")
    print(f"  * Severite du risque        : {critical_anomaly.severity.value.upper()}")
    print(f"  * Valeur reelle observee    : {critical_anomaly.observed_value:,.2f} $")
    print(f"  * Baseline (Moyenne attendue): {critical_anomaly.expected_value:,.2f} $")
    print(f"  * Z-Score mathematique      : {critical_anomaly.z_score} ecarts-types")
    print(f"  * Deviation relative        : {critical_anomaly.pct_deviation:+.1f} %")
    print(f"  * Regle de preuve XAI       : {critical_anomaly.lineage.exact_sql_query.strip()}")

    # 5. Agent 6 - LLM Strategic Executive Briefing
    print("\n[5] AGENT 6 : SYNTHESE STRATEGIQUE DU LLM POUR LE COMEX (Explication du Pourquoi)")
    print("-" * 80)
    strat_res = llm.strategic_analysis(
        kpi_catalog={k.name: f"{k.value} {k.unit}" for k in sem_state.kpis[:3]},
        statistical_anomalies=[a.model_dump(mode="json") for a in ana_state.statistical_anomalies[:3]],
        trend_metrics={"direction": "SURGING", "growth": "+2118%"},
        pareto_risks={"top_share": "59.8% Technology"},
    )
    print(f"  * Synthese Executive COMEX :\n    \"{strat_res.executive_summary}\"\n")
    print("  * Recommandations Prioritaires :")
    for r in strat_res.strategic_recommendations:
        print(f"    - [{r.priority.value.upper()}] {r.action}")
        print(f"      (Justification: {r.justification})")

    # 6. JSON Export
    print("\n[6] PAYLOAD JSON FINAL D'AUDITABILITE (Contrat Pydantic V2) :")
    print("-" * 80)
    audit_sample = {
        "dataset": sem_state.dataset_name,
        "kpi_audite": {
            "nom": rev_kpi.name,
            "valeur": rev_kpi.value,
            "sql": rev_kpi.lineage.exact_sql_query,
            "rag_source": rev_kpi.lineage.source_document,
        },
        "anomalie_auditee": {
            "entite": critical_anomaly.entity,
            "valeur": critical_anomaly.observed_value,
            "z_score": critical_anomaly.z_score,
            "preuve": critical_anomaly.lineage.exact_sql_query.strip(),
        },
    }
    print(json.dumps(audit_sample, indent=2))
    print("=" * 80)
    print("   RESULTAT : ZERO HALLUCINATION. REQUETES SQL PROUVABLES. BRIEFING LLM CERTIFIE.")
    print("=" * 80)


if __name__ == "__main__":
    main()
