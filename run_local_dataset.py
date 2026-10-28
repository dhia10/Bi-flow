"""
=============================================================================
 BI-Flow — Test Local du Pipeline LangGraph sur vos Jeux de Données
=============================================================================
Exécute les 7 agents de production via l'orchestrateur LangGraph :
  1. Data Profiler (agent_clean)
  2. Data Quality & Cleaning avec boucle conditionnelle (agent_clean)
  3. ETL Dimensionnel (etl)
  4. BI Semantic & KPI Engine (Agent 5 - DuckDB & RAG)
  5. BI Analyst (Agent 6 - Z-Score, Pareto, Tukey IQR)
  6. Dashboard Generator (generator)
  7. XAI Auditor & Explicabilité

Usage:
  py -3.11 run_local_dataset.py [chemin_vers_csv] [domaine]
Exemples:
  py -3.11 run_local_dataset.py bi_pipeline/data/mock_clean_data.csv retail
  py -3.11 run_local_dataset.py data/Superstore.csv retail
=============================================================================
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

# Encodage console UTF-8 sous Windows
sys.stdout.reconfigure(encoding="utf-8")

# Ajout des répertoires au sys.path
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "Orchestrator") not in sys.path:
    sys.path.insert(0, str(_ROOT / "Orchestrator"))

from Orchestrator.agents.nodes import get_production_agents
from Orchestrator.orchestrator.orchestrator import run_pipeline


def main() -> None:
    dataset_path = sys.argv[1] if len(sys.argv) > 1 else "bi_pipeline/data/mock_clean_data.csv"
    domain = sys.argv[2] if len(sys.argv) > 2 else "retail"

    p = Path(dataset_path)
    if not p.is_file():
        print(f"[ERREUR] Le fichier '{dataset_path}' n'existe pas.")
        sys.exit(1)

    print("=" * 80)
    print(" 🚀 BI-Flow — Test Local du Pipeline Multi-Agents LangGraph")
    print("=" * 80)
    print(f" Dataset : {p.resolve()}")
    print(f" Domaine : {domain}")
    print("=" * 80)

    t0 = time.time()
    agents = get_production_agents()
    print(" Initialisation des 7 agents de production...")

    result = run_pipeline(agents, dataset_ref=str(p.resolve()), domain=domain)
    duration = time.time() - t0

    print("\n" + "=" * 80)
    print(f" ✅ Pipeline terminé avec succès en {duration:.2f}s !")
    print("=" * 80)

    # Affichage du parcours des nœuds
    trace = result.get("trace", [])
    print("\n📍 Trajet des Nœuds Exécutés :")
    for t in trace:
        print(f"   • {t.node:<12} (Passage {t.attempt}) -> Statut: {t.status:<7} ({t.duration_s:.3f}s)")

    # KPIs calculés
    kpis_data = result.get("kpi_catalog") or {}
    proofs = kpis_data.get("proofs", [])
    print(f"\n📊 KPIs Calculés par DuckDB & Agent 5 ({len(proofs)}) :")
    for p in proofs[:8]:
        name = p.get("kpi_name", "KPI")
        val = p.get("value", 0)
        unit = p.get("unit", "")
        print(f"   - {name}: {val:,.2f} {unit}")

    # Anomalies détectées
    insights = result.get("insights") or {}
    anomalies = insights.get("anomalies", []) if isinstance(insights, dict) else (insights if isinstance(insights, list) else [])
    print(f"\n🔍 Analyse Statistique & Anomalies (Agent 6) ({len(anomalies)} alertes) :")
    for ins in anomalies[:5]:
        ent = ins.get("entity", "Inconnu")
        sev = ins.get("severity", "MEDIUM")
        exp = ins.get("business_explanation") or ins.get("description", "")
        z = ins.get("z_score")
        z_str = f" (Z={z:+.2f})" if z is not None else ""
        print(f"   [{sev}] {ent}{z_str}: {exp}")

    # Rapport XAI
    xai = result.get("xai_report") or {}
    print(f"\n🛡️ Décision Finale & XAI : {xai.get('summary', 'Conforme')}")

    # Fichiers JSON générés
    print("\n📦 Fichiers JSON inter-agents sauvegardés :")
    print("   - runs/state.json         (État complet du graphe)")
    print("   - runs/agent_messages.json (Payloads transmis entre agents)")
    print("=" * 80)


if __name__ == "__main__":
    main()
