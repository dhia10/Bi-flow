from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import pandas as pd

from src.pipelines.query_pipeline import ProductionQueryPipeline

logging.basicConfig(level=logging.WARNING)


def build_olist_mart(base_dir: Path, sample_limit: int = 15000) -> pd.DataFrame:
    orders_p = base_dir / "olist_orders_dataset.csv"
    items_p = base_dir / "olist_order_items_dataset.csv"
    products_p = base_dir / "olist_products_dataset.csv"
    trans_p = base_dir / "product_category_name_translation.csv"
    customers_p = base_dir / "olist_customers_dataset.csv"

    orders = pd.read_csv(
        orders_p,
        usecols=["order_id", "customer_id", "order_status", "order_purchase_timestamp"],
    )
    orders = orders[orders["order_status"] == "delivered"].head(sample_limit)

    items = pd.read_csv(
        items_p,
        usecols=["order_id", "order_item_id", "product_id", "price", "freight_value"],
    )
    products = pd.read_csv(products_p, usecols=["product_id", "product_category_name"])
    customers = pd.read_csv(
        customers_p,
        usecols=["customer_id", "customer_state", "customer_city"],
    )

    df = items.merge(orders, on="order_id", how="inner")
    df = df.merge(products, on="product_id", how="left")
    df = df.merge(customers, on="customer_id", how="left")

    if trans_p.is_file():
        trans = pd.read_csv(trans_p)
        df = df.merge(trans, on="product_category_name", how="left")
        df["category"] = (
            df["product_category_name_english"]
            .fillna(df["product_category_name"])
            .fillna("other")
        )
    else:
        df["category"] = df["product_category_name"].fillna("other")

    df = df.rename(
        columns={
            "price": "sales",
            "order_item_id": "quantity",
            "order_purchase_timestamp": "order_date",
            "customer_state": "region",
        }
    )
    return df


def main():
    base_dir = Path(__file__).resolve().parents[1]

    print("=" * 84)
    print("     BI-FLOW OLIST : PIPELINE PRODUCTION RAG & TEXT-TO-SQL (MULTI-AGENTS)")
    print("=" * 84)

    # Build analytical mart
    t0 = time.perf_counter()
    mart = build_olist_mart(base_dir, sample_limit=25000)
    build_time = time.perf_counter() - t0
    print(
        f"\n[1] DONNEES CHARGEES : {len(mart):,} lignes de transactions Olist "
        f"({mart['order_id'].nunique():,} commandes) en {build_time:.2f}s"
    )
    print(f"    * Colonnes : {', '.join(list(mart.columns)[:8])}...")

    # Run Production Pipeline (src/)
    pipeline = ProductionQueryPipeline()
    start_total = time.perf_counter()
    res = pipeline.run(
        mart,
        dataset_name="Olist Brazilian E-Commerce",
        query_intent="retail ecommerce kpi sales revenue profit orders",
        force_refresh=True,
    )
    total_ms = round((time.perf_counter() - start_total) * 1000.0, 2)

    # [2] Hybrid Retrieval & Reranking
    print("\n[2] HYBRID RETRIEVAL & RERANKING (FAISS Dense + BM25 Lexical + RRF)")
    print("-" * 84)
    print(f"  * Domaine Identifie        : {res.detected_domain}")
    print(f"  * Tier de Certification    : {res.retrieval_tier}")
    print(f"  * Score Reranker Final     : {res.retrieval_relevance_score:.4f}")

    # [3] Agent 5
    print("\n[3] AGENT 5 : MAPPAGE SEMANTIQUE & EXECUTION DUCKDB (:memory:)")
    print("-" * 84)
    print(f"  * Modele LLM               : {pipeline.cfg['models']['primary_llm']}")
    for m in res.semantic_mappings:
        print(
            f"    --> [{m.concept}] => '{m.physical_column}' "
            f"(Confiance: {m.confidence_score * 100:.0f}%)"
        )
    if res.duckdb_proofs:
        for p in res.duckdb_proofs:
            val_str = (
                f"{p.value:,.2f}" if isinstance(p.value, float) else str(p.value)
            )
            print(f"\n  * {p.kpi_name} = {val_str} {p.unit or ''}")
            print(f"    SQL  : {p.exact_sql}")
            print(f"    Chunk: {p.source_chunk_id}  |  Latence: {p.latency_ms:.2f} ms")

    # [4] Agent 6 — Anomalies
    print("\n[4] AGENT 6 : DETECTION D'ANOMALIES (Z-Score / Tukey)")
    print("-" * 84)
    print(f"  * Total Anomalies : {len(res.anomalies)}")
    for a in res.anomalies[:5]:
        z_str = f"{a.z_score:+.2f} std" if a.z_score is not None else "N/A"
        print(
            f"  * [{a.severity.value.upper()}] {a.entity} ({a.metric}): "
            f"{a.observed_value:,.2f} $ | baseline {a.baseline_value:,.2f} $ | "
            f"Z={z_str} | dev={a.deviation_pct:+.1f}%"
        )

    # [5] Grounded Synthesis
    print("\n[5] SYNTHESE COMEX ANCREE (Grounded Synthesis avec Citations)")
    print("-" * 84)
    preview = res.executive_narrative[:400].replace("\n", "\n    ")
    print(f"    {preview}...")
    print(f"\n  * Citations : {res.grounded_citations}")
    print(f"\n  * Recommandations Strategiques Prioritaires ({len(res.strategic_recommendations)}) :")
    for r in res.strategic_recommendations:
        print(f"    - [{r.priority.value.upper()}] {r.action}")
        print(f"      Justification : {r.justification}")

    # [6] JSON audit payload
    print("\n[6] PAYLOAD JSON FINAL D'AUDITABILITE (Pydantic V2) :")
    print("-" * 84)
    audit = {
        "dataset": res.dataset_name,
        "domain": res.detected_domain,
        "retrieval_score": res.retrieval_relevance_score,
        "tier": res.retrieval_tier,
        "kpi_count": len(res.duckdb_proofs),
        "anomaly_count": len(res.anomalies),
        "citations_count": len(res.grounded_citations),
    }
    print(json.dumps(audit, indent=2, ensure_ascii=False))

    # [7] Observability & RAGAS Evaluation
    print("\n[7] OBSERVABILITE & EVALUATION RAG (RAGAS & TRACING)")
    print("-" * 84)
    print("  * Latences par Etape :")
    for step, lat in res.step_latencies_ms.items():
        print(f"    - {step:<35} : {lat:>8.2f} ms")
    print(f"    - {'duree_totale_pipeline_ms':<35} : {total_ms:>8.2f} ms")
    print(f"  * Cache Hit : {res.cache_hit}")
    print("  * Metriques RAGAS :")
    print(f"    - Faithfulness            : {res.eval_metrics.faithfulness * 100:.1f} %")
    print(f"    - Context Recall@k        : {res.eval_metrics.context_recall * 100:.1f} %")
    print(f"    - SQL Exact Match         : {res.eval_metrics.sql_exact_match * 100:.1f} %")
    print(f"    - Grounded Claim Ratio    : {res.eval_metrics.grounded_claim_ratio * 100:.1f} %")
    print("=" * 84)
    print("                       EXECUTION VALIDEE AVEC SUCCES")
    print("=" * 84)


if __name__ == "__main__":
    main()
