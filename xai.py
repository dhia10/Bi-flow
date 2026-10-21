from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd
from src.pipelines.query_pipeline import ProductionQueryPipeline


def main():
    print("=" * 84)
    print("      BI-FLOW : ARCHITECTURE RAG & TEXT-TO-SQL DE PRODUCTION (MULTI-AGENTS)")
    print("=" * 84)

    # 1. Load Data
    data_path = ROOT_DIR / "bi_pipeline" / "data" / "mock_clean_data.csv"
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_file():
        data_path = Path(sys.argv[1])

    df = pd.read_csv(data_path)
    print(f"\n[1] DONNEES CHARGEES : {len(df)} transactions ({data_path.name})")
    print(f"    * Colonnes detectees : {', '.join(list(df.columns)[:7])}...")

    # Initialize Production Pipeline
    pipeline = ProductionQueryPipeline()

    # Run Pipeline
    start_total = time.perf_counter()
    res = pipeline.run(df, dataset_name="Superstore Retail", query_intent="retail ecommerce kpi sales revenue profit", force_refresh=True)
    total_duration_ms = round((time.perf_counter() - start_total) * 1000.0, 2)

    # 2. Hybrid Retrieval & Reranking Metrics
    print("\n[2] HYBRID RETRIEVAL & RERANKING (FAISS Dense + BM25 Lexical + RRF + Rerank)")
    print("-" * 84)
    print("  * Index Dense Vectoriel    : FAISS IndexFlatIP (Normalisation L2)")
    print("  * Index Lexical            : BM25Okapi (rank_bm25 sur colonnes, synonymes et SQL)")
    print("  * Algorithme de Fusion     : Fusion Hybride Ponderee (60% Dense + 40% Lexical)")
    print("  * Reranker Semantique      : SemanticReranker (Couverture ontologique + Alignement)")
    print(f"  * Domaine Identifie        : {res.detected_domain}")
    print(f"  * Tier de Certification    : {res.retrieval_tier}")
    print(f"  * Score RAG Calibre Final  : {res.retrieval_relevance_score:.4f} (Calcul Dynamique)")

    # 3. Agent 5 - Ontological Mapping & DuckDB Execution (Full KPI Scorecard)
    print(f"\n[3] AGENT 5 : MAPPAGE SÉMANTIQUE & EXECUTION DUCKDB (:memory:) - {len(res.duckdb_proofs)} KPIS")
    print("-" * 84)
    primary_model = pipeline.cfg["models"]["primary_llm"]
    fallback_model = pipeline.cfg["models"]["fallback_llm"]
    print(f"  * Moteur de Raisonnement   : LLM ({primary_model} / Fallback: {fallback_model})")
    print("  * Mappages Ontologiques Concept Metier -> Colonne Physique :")
    for m in res.semantic_mappings:
        print(f"    --> [{m.concept}] => '{m.physical_column}' (Confiance: {m.confidence_score*100:.0f}%)")

    print("\n  * CATALOGUE COMPLET DES KPIS DETERMINISTES CERTIFIES DUCKDB :")
    for idx, p in enumerate(res.duckdb_proofs, 1):
        val_str = f"{p.value:,.2f}" if isinstance(p.value, float) else f"{p.value:,}" if isinstance(p.value, int) else str(p.value)
        print(f"    {idx}. {p.kpi_name:<28} = {val_str:>12} {p.unit or '':<8} | Latence: {p.latency_ms:>5.2f} ms")
        print(f"       SQL: {p.exact_sql}")

    # 4. Agent 6 - Statistical Mining (Z-Score, Tukey & Pareto)
    print(f"\n[4] AGENT 6 : MINING STATISTIQUE & DETECTION D'ANOMALIES (Z-Score / Tukey / Pareto) - {len(res.anomalies)} DETECTEES")
    print("-" * 84)
    if res.anomalies:
        for a in res.anomalies:
            z_s = f"{a.z_score:+.2f} std" if a.z_score is not None else "N/A"
            print(f"  * [{a.severity.value.upper()}] Entite '{a.entity}' ({a.dimension} / {a.metric})")
            print(f"    - Valeur Observee  : {a.observed_value:,.2f} $ (Moyenne attendue : {a.baseline_value:,.2f} $)")
            print(f"    - Ecart-Type Z     : {z_s}  |  Deviation : {a.deviation_pct:+.1f} %")
            print(f"    - Preuve Regle     : {a.proof_rule}")
            print(f"    - Diagnostic       : {a.description}")
    else:
        print("  * Aucune anomalie critique detectee au-dela des seuils Z-Score/IQR.")

    # 5. Agent 6 - LLM Grounded Synthesis with Citations & Prioritized Recommendations
    print("\n[5] AGENT 6 : SYNTHÈSE STRATÉGIQUE COMEX ANCRÉE (Grounded Synthesis)")
    print("-" * 84)
    print("  * Synthese Executive COMEX (avec Citations RAG explicites) :")
    print(f"    \"{res.executive_narrative}\"\n")
    print(f"  * Citations RAG Utilisees   : {', '.join(res.grounded_citations) if res.grounded_citations else 'None'}")
    print(f"  * Recommandations Strategiques Prioritaires ({len(res.strategic_recommendations)}) :")
    for r in res.strategic_recommendations:
        print(f"    - [{r.priority.value.upper()}] {r.action}")
        print(f"      Justification : {r.justification}")

    # 6. JSON Audit Payload (Pydantic V2)
    print("\n[6] PAYLOAD JSON FINAL D'AUDITABILITÉ (Contrat Pydantic V2) :")
    print("-" * 84)
    audit_sample = {
        "dataset_name": res.dataset_name,
        "domain": res.detected_domain,
        "retrieval_relevance_score": res.retrieval_relevance_score,
        "total_kpis": len(res.duckdb_proofs),
        "total_anomalies": len(res.anomalies),
        "total_recommendations": len(res.strategic_recommendations),
        "citations_rag": res.grounded_citations,
    }
    print(json.dumps(audit_sample, indent=2, ensure_ascii=False))

    # 7. Observability & RAGAS Evaluation
    print("\n[7] OBSERVABILITÉ & ÉVALUATION RAG (RAGAS & TRACING)")
    print("-" * 84)
    print("  * Latences Detaillees par Etape (ms) :")
    for step, lat in res.step_latencies_ms.items():
        print(f"    - {step:<35} : {lat:>7.2f} ms")
    print(f"  * Semantic Cache Hit       : {res.cache_hit} (Stockage SQLite persistant)")
    print("  * Metriques d'Evaluation RAG (RAGAS Framework) :")
    print(f"    - Faithfulness Score       : {res.eval_metrics.faithfulness * 100:.1f} % (Verification regex DuckDB)")
    print(f"    - Context Recall@k         : {res.eval_metrics.context_recall * 100:.1f} %")
    print(f"    - SQL Exact Match Score    : {res.eval_metrics.sql_exact_match * 100:.1f} %")
    print(f"    - Grounded Claim Ratio     : {res.eval_metrics.grounded_claim_ratio * 100:.1f} %")
    print("=" * 84)
    print("                       EXECUTION VALIDEE AVEC SUCCES")
    print("=" * 84)


if __name__ == "__main__":
    main()
