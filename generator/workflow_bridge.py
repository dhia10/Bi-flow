"""
Workflow Bridge for BI Studio & LangGraph Multi-Agents
=============================================================================
Ce module assure la synchronisation bidirectionnelle entre le pipeline
multi-agents LangGraph (runs/state.json, DuckDB proofs, Agent 6 Anomalies)
et l'interface visuelle Apache Superset / Power BI de generator/ :
  1. Synchronise le dataset actif réel (CSV / Parquet)
  2. Injecte les 5 à 8 KPIs déterministes DuckDB de l'Agent 5
  3. Génère les auto_visuals (Bar, Line, Pie, Cards) avec les vraies données
  4. Met à jour generator/kpis_catalog.json et generator/visuals_state.json
  5. Remplace le mock PwC de data_store.js par les vraies métriques du workflow
=============================================================================
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional

import duckdb
import numpy as np
import pandas as pd

log = logging.getLogger("bi_flow.workflow_bridge")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def find_repo_root() -> Path:
    p = Path(__file__).resolve().parent
    for _ in range(4):
        if (p / "runs").exists() or (p / "bi_pipeline").exists():
            return p
        p = p.parent
    return Path.cwd()


def sync_workflow_to_studio(repo_root: Optional[Path] = None, state_override: Optional[dict] = None) -> dict:
    root = repo_root or find_repo_root()
    gen_dir = root / "generator"
    gen_dir.mkdir(parents=True, exist_ok=True)
    uploads_dir = gen_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # Nettoyage préventif des anciens fichiers uploadés
    for old_f in uploads_dir.iterdir():
        if old_f.is_file() and old_f.name != "active_dataset.csv":
            try:
                old_f.unlink()
            except Exception:
                pass

    # 1. Charger l'état le plus récent du pipeline LangGraph
    state = state_override
    state_file = root / "runs" / "state.json"
    if not state and state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception as e:
            log.warning("Erreur de lecture de state.json: %s", e)

    if not state:
        state = {}

    # 2. Localiser et charger le DataFrame du dataset actif
    df = None
    dataset_name = state.get("domain", "Enterprise Dataset")
    clean_data_path = state.get("clean_data")
    dataset_ref = state.get("dataset_ref")

    candidates = [
        clean_data_path,
        dataset_ref,
        root / "bi_pipeline" / "data" / "mock_clean_data.csv",
    ]

    for cand in candidates:
        if not cand:
            continue
        p = Path(cand)
        if not p.is_absolute():
            p = root / p
        if p.exists():
            try:
                if p.suffix.lower() == ".parquet":
                    df = pd.read_parquet(p)
                else:
                    df = pd.read_csv(p)
                dataset_name = p.stem.replace("dataset_", "").replace("uploaded_", "")
                log.info("Dataset chargé depuis %s (%d lignes, %d colonnes)", p.name, len(df), len(df.columns))
                # Sauvegarder une copie CSV propre dans generator/uploads/
                active_csv = uploads_dir / "active_dataset.csv"
                df.to_csv(active_csv, index=False)
                break
            except Exception as e:
                log.warning("Impossible de lire %s: %s", cand, e)

    if df is None or len(df) == 0:
        log.warning("Aucun dataset trouvé, génération d'un dataset de fallback...")
        df = pd.DataFrame({
            "id": range(1, 11),
            "category": ["A", "B", "C", "A", "B", "C", "A", "B", "C", "A"],
            "sales": [100, 150, 200, 120, 180, 220, 130, 170, 210, 140],
            "date": pd.date_range("2024-01-01", periods=10).astype(str),
        })

    # Nom de la table
    table_name = state.get("data_model", {}).get("fact_table", "FACT_DATA").upper()
    if table_name.lower().startswith("fact_"):
        pass
    else:
        table_name = f"FACT_{table_name}"

    # 3. Récupérer les KPIs calculés par DuckDB dans le workflow (Agent 5)
    proofs = state.get("kpi_catalog", {}).get("proofs", [])
    anomalies = state.get("insights", {}).get("anomalies", [])

    # 4. DuckDB Aggregations pour les visuels Superset
    con = duckdb.connect(":memory:")
    con.register("df", df)

    # Identifier colonnes clés
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not any(k in c.lower() for k in ("_id", "sku", "_key", "_code"))]
    cat_cols = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c]) and not any(k in c.lower() for k in ("date", "time", "id", "key", "sku", "url")) and df[c].nunique() > 1]
    date_cols = [c for c in df.columns if any(k in c.lower() for k in ("date", "time", "timestamp", "year", "day")) or pd.api.types.is_datetime64_any_dtype(df[c])]

    primary_measure = num_cols[0] if num_cols else df.columns[0]
    primary_dim = cat_cols[0] if cat_cols else (df.columns[1] if len(df.columns) > 1 else df.columns[0])
    secondary_dim = cat_cols[1] if len(cat_cols) > 1 else primary_dim
    date_col = date_cols[0] if date_cols else None

    # Agrégation Bar: primary_dim x primary_measure
    bar_data = []
    try:
        q_bar = f'SELECT CAST("{primary_dim}" AS VARCHAR) AS "{primary_dim}", ROUND(CAST(SUM("{primary_measure}") AS DOUBLE), 2) AS "{primary_measure}" FROM df WHERE "{primary_dim}" IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 10'
        bar_data = con.execute(q_bar).df().to_dict("records")
    except Exception as e:
        log.warning("Agrégation bar: %s", e)

    # Agrégation Time Series
    time_data = []
    if date_col:
        try:
            q_time = f'SELECT CAST("{date_col}" AS VARCHAR) AS "{date_col}", ROUND(CAST(SUM("{primary_measure}") AS DOUBLE), 2) AS "{primary_measure}" FROM df WHERE "{date_col}" IS NOT NULL GROUP BY 1 ORDER BY 1 ASC LIMIT 35'
            time_data = con.execute(q_time).df().to_dict("records")
        except Exception as e:
            log.warning("Agrégation time: %s", e)

    # Agrégation Pie (Distribution Secondary Dim ou Top Categories)
    pie_data = []
    try:
        q_pie = f'SELECT CAST("{secondary_dim}" AS VARCHAR) AS "{secondary_dim}", ROUND(CAST(SUM("{primary_measure}") AS DOUBLE), 2) AS "{primary_measure}" FROM df WHERE "{secondary_dim}" IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 6'
        pie_data = con.execute(q_pie).df().to_dict("records")
    except Exception as e:
        log.warning("Agrégation pie: %s", e)

    # 5. Construire les KPIs formels
    kpis_list = []
    if proofs:
        for i, p in enumerate(proofs):
            kpi_name = p.get("kpi_name", f"KPI_{i}")
            val = p.get("value") if p.get("value") is not None else p.get("calculated_value", 0)
            unit = p.get("unit", "")
            exact_sql = p.get("exact_sql", f'SELECT SUM("{primary_measure}") FROM df')
            col_used = (p.get("columns_used") or [primary_measure])[0]
            clean_id = re.sub(r"[^A-Za-z0-9_]", "", kpi_name)[:22].upper()
            is_card = i < 5
            c_type = "card" if is_card else ("bar" if i % 2 == 0 else "line")
            s_type = "big_number_total" if is_card else ("echarts_bar" if i % 2 == 0 else "echarts_line")

            kpis_list.append({
                "id": f"KPI_{table_name}_{i}_{clean_id}",
                "name": kpi_name,
                "domain": dataset_name,
                "category": p.get("category", "Général"),
                "description": f"Métrique calculée DuckDB : {kpi_name} ({unit})",
                "source_table": table_name,
                "table_name": table_name,
                "aggregation_type": "CALC",
                "metric_column": col_used,
                "dimension_column": primary_dim,
                "chart_type": c_type,
                "superset_chart_type": s_type,
                "sql_superset": exact_sql,
                "raw_value": val,
                "current_value_formatted": f"{val:,.2f} {unit}".strip() if isinstance(val, (int, float)) else f"{val} {unit}".strip(),
                "suggested_prompts": [kpi_name, f"Analyse de {kpi_name}", f"Évolution de {kpi_name}"],
                "active": True,
                "source_file": dataset_name,
                "top_n": 10,
                "dax_measure": f"{kpi_name} = {val} -- [{unit}]",
                "api_endpoint": {"method": "GET", "path": f"/api/v1/kpi/{i}"},
                "_data": bar_data if i == 0 else (time_data if i == 1 else (pie_data if i == 2 else []))
            })
    else:
        # Générer KPIs par défaut sur les colonnes numériques du dataset
        for i, col in enumerate(num_cols[:5]):
            total_val = float(df[col].sum())
            clean_id = re.sub(r"[^A-Za-z0-9_]", "", col)[:22].upper()
            kpis_list.append({
                "id": f"KPI_{table_name}_{i}_{clean_id}",
                "name": f"Total {col.replace('_', ' ').title()}",
                "domain": dataset_name,
                "category": "Général",
                "description": f"Somme DuckDB de {col}",
                "source_table": table_name,
                "table_name": table_name,
                "aggregation_type": "SUM",
                "metric_column": col,
                "dimension_column": primary_dim,
                "chart_type": "card",
                "superset_chart_type": "big_number_total",
                "sql_superset": f'SELECT SUM("{col}") AS "{col}" FROM "{table_name}";',
                "raw_value": total_val,
                "current_value_formatted": f"{total_val:,.2f}",
                "suggested_prompts": [col, f"Total {col}"],
                "active": True,
                "source_file": dataset_name,
                "top_n": 10,
                "dax_measure": f"Total {col} = SUM('{table_name}'[{col}])",
                "api_endpoint": {"method": "GET", "path": f"/api/v1/kpi/{i}"},
                "_data": bar_data if i == 0 else (time_data if i == 1 else [])
            })

    # 6. Construire les auto_visuals pour BI Studio (Visual Grid)
    auto_visuals = []

    # Visual 1: Bar Chart (Dimension x Mesure)
    if bar_data:
        auto_visuals.append({
            "id": f"vis-bar-{primary_dim.lower()}",
            "kpi_id": f"KPI_{table_name}_BAR",
            "title": f"Distribution de {primary_measure.replace('_', ' ').title()} par {primary_dim.replace('_', ' ').title()} (Top 10)",
            "subtitle": f"Dataset: {dataset_name} | Apache Superset ECharts Bar",
            "chartType": "bar",
            "domain": dataset_name,
            "data": bar_data,
            "labelField": primary_dim,
            "valueField": primary_measure,
            "metricLabel": primary_measure,
            "sql": f'SELECT "{primary_dim}", SUM("{primary_measure}") AS "{primary_measure}" FROM "{table_name}" GROUP BY "{primary_dim}" ORDER BY "{primary_measure}" DESC LIMIT 10;',
            "dax": f"{primary_measure} By {primary_dim} = CALCULATE(SUM('{table_name}'[{primary_measure}]))",
            "superset": {"viz_type": "echarts_timeseries_bar", "metric": primary_measure},
            "active": True,
            "source_file": dataset_name,
            "top_n": 10
        })

    # Visual 2: Time Series Chart (Date x Mesure)
    if time_data and date_col:
        auto_visuals.append({
            "id": f"vis-line-{date_col.lower()}",
            "kpi_id": f"KPI_{table_name}_LINE",
            "title": f"Tendance Chronologique de {primary_measure.replace('_', ' ').title()} ({date_col})",
            "subtitle": f"Dataset: {dataset_name} | Apache Superset ECharts Line",
            "chartType": "line",
            "domain": dataset_name,
            "data": time_data,
            "labelField": date_col,
            "valueField": primary_measure,
            "metricLabel": primary_measure,
            "sql": f'SELECT "{date_col}", SUM("{primary_measure}") AS "{primary_measure}" FROM "{table_name}" GROUP BY "{date_col}" ORDER BY "{date_col}" ASC;',
            "dax": f"{primary_measure} Over Time = CALCULATE(SUM('{table_name}'[{primary_measure}]))",
            "superset": {"viz_type": "echarts_timeseries_line", "metric": primary_measure},
            "active": True,
            "source_file": dataset_name,
            "top_n": 35
        })

    # Visual 3: Pie Chart (Répartition Top 6)
    if pie_data:
        auto_visuals.append({
            "id": f"vis-pie-{secondary_dim.lower()}",
            "kpi_id": f"KPI_{table_name}_PIE",
            "title": f"Part de Marché par {secondary_dim.replace('_', ' ').title()} (Top 6)",
            "subtitle": f"Dataset: {dataset_name} | Apache Superset Donut / Pie",
            "chartType": "pie",
            "domain": dataset_name,
            "data": pie_data,
            "labelField": secondary_dim,
            "valueField": primary_measure,
            "metricLabel": primary_measure,
            "sql": f'SELECT "{secondary_dim}", SUM("{primary_measure}") AS "{primary_measure}" FROM "{table_name}" GROUP BY "{secondary_dim}" ORDER BY "{primary_measure}" DESC LIMIT 6;',
            "dax": f"{primary_measure} Share = DIVIDE(SUM('{table_name}'[{primary_measure}]), CALCULATE(SUM('{table_name}'[{primary_measure}]), ALL('{table_name}')))",
            "superset": {"viz_type": "pie", "metric": primary_measure},
            "active": True,
            "source_file": dataset_name,
            "top_n": 6
        })

    # Visual 4: Carte d'Alerte Anomalies (Agent 6)
    if anomalies:
        top_anom = anomalies[0]
        ent = top_anom.get("entity", "N/A")
        z = top_anom.get("z_score", 0)
        desc = top_anom.get("description", "Divergence statistique détectée")
        auto_visuals.append({
            "id": "vis-card-anomaly-alert",
            "kpi_id": f"KPI_{table_name}_ANOMALY",
            "title": f"Alerte Statistique COMEX : {ent}",
            "subtitle": f"Agent 6 Analyst | Tukey & Z-Score = {z:.2f}",
            "chartType": "card",
            "domain": dataset_name,
            "data": [{"entity": ent, "z_score": z, "alert": desc}],
            "labelField": "entity",
            "valueField": "z_score",
            "metricLabel": "Z-Score",
            "sql": "-- Détection automatique IQR & Z-score multi-agents",
            "dax": f"ZScore Outlier = {z}",
            "superset": {"viz_type": "big_number_total", "metric": "z_score"},
            "active": True,
            "source_file": dataset_name,
            "cardValue": z,
            "cardValueFormatted": f"Z = {z:+.2f}",
            "cardBenchmark": desc
        })

    # 7. Écriture de generator/kpis_catalog.json
    catalog_payload = {
        "metadata": {
            "version": "2.0.0",
            "active_dataset": dataset_name,
            "table_name": table_name,
            "n_rows": len(df),
            "columns": list(df.columns),
            "datasets": [dataset_name],
            "last_updated": pd.Timestamp.now().isoformat(),
            "generated_by": "Bi-Flow LangGraph Pipeline (DuckDB + Analyst Agents)",
            "dashboard_background": "#0a0e17"
        },
        "kpis": kpis_list,
        "auto_visuals": auto_visuals,
        "prompt_visuals": []
    }

    catalog_path = gen_dir / "kpis_catalog.json"
    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump(catalog_payload, f, indent=2, ensure_ascii=False)
    log.info("Écrit: %s (%d KPIs, %d visuels)", catalog_path.name, len(kpis_list), len(auto_visuals))

    # 8. Écriture de generator/visuals_state.json
    visuals_state_path = gen_dir / "visuals_state.json"
    with open(visuals_state_path, "w", encoding="utf-8") as f:
        json.dump({"visuals": auto_visuals}, f, indent=2, ensure_ascii=False)
    log.info("Écrit: %s", visuals_state_path.name)

    # 9. Remplacement de data_store.js et bi_data_store.json (remplacement du mock PwC)
    summary_dict = {
        "dataset_name": dataset_name,
        "total_records": len(df),
        "table_name": table_name,
        "anomalies_count": len(anomalies)
    }
    for k in kpis_list[:6]:
        summary_dict[k["id"].lower()] = k["raw_value"]

    bi_store = {
        "summary": summary_dict,
        "primary_dimension": bar_data,
        "time_series": time_data,
        "distribution": pie_data,
        "anomalies": anomalies
    }

    with open(gen_dir / "bi_data_store.json", "w", encoding="utf-8") as f:
        json.dump(bi_store, f, indent=2, ensure_ascii=False)

    data_store_js = f"""// Synchronisé automatiquement avec le pipeline LangGraph Multi-Agents
window.BI_DATA_STORE = {json.dumps(bi_store, indent=2, ensure_ascii=False)};
window.KPIS_CATALOG = {json.dumps(catalog_payload, indent=2, ensure_ascii=False)};
"""
    with open(gen_dir / "data_store.js", "w", encoding="utf-8") as f:
        f.write(data_store_js)
    log.info("Écrit: data_store.js & bi_data_store.json avec les vraies métriques du workflow.")

    return {
        "status": "success",
        "dataset": dataset_name,
        "table": table_name,
        "n_rows": len(df),
        "kpis_count": len(kpis_list),
        "visuals_count": len(auto_visuals)
    }


if __name__ == "__main__":
    res = sync_workflow_to_studio()
    print(f"\n[OK] Synchronisation réussie : {res}")
