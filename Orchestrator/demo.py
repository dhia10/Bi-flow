"""
DÉMO DE L'ORCHESTRATEUR — à lancer devant le prof :   python demo.py

Trois scénarios, avec des agents-jouets à la place des vrais agents :
  1. Nominal        : la qualité relance une fois, puis tout passe.
  2. Boucle bornée  : la qualité reste sale -> 2 relances max, puis on avance.
  3. Échec          : l'ETL plante -> saut direct vers XAI, qui explique.

Produit aussi :
  runs/graph.mmd    : le graphe compilé (Mermaid) -> à coller sur mermaid.live
  runs/state.json   : l'état final du scénario 1
"""
import json
import logging
from dataclasses import asdict, is_dataclass
from pathlib import Path

from orchestrator.orchestrator import build_graph, run_pipeline
from tests.toy_agents import failing_agent, toy_agents

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
RUNS = Path("runs")
RUNS.mkdir(exist_ok=True)


def show(title: str, final: dict) -> None:
    print("\n" + "=" * 72)
    print(f" {title}   (run_id={final['run_id']})")
    print("=" * 72)
    print("Ordre exécuté :", " -> ".join(t.node for t in final["trace"]))
    print("\nTrace (écrite par l'orchestrateur) :")
    for t in final["trace"]:
        extra = f"  [{t.message}]" if t.message else ""
        print(f"  {t.node:<10} passage {t.attempt}  {t.status:<8} {t.duration_s:.4f}s{extra}")
    print("\nDécisions de l'orchestrateur :")
    orch = [d for d in final["decision_log"] if d.agent == "Orchestrator"]
    for d in orch or []:
        print(f"  - {d.action}\n      pourquoi : {d.rationale}")
    if not orch:
        print("  (aucune : chemin nominal)")
    print("\nCompteur de passages :", final["control"].runs)
    print("Rapport XAI          :", final["xai_report"]["verdict"],
          "| erreurs :", final["xai_report"]["erreurs"] or "aucune")


def to_json(o):
    return asdict(o) if is_dataclass(o) else str(o)


if __name__ == "__main__":
    # 1. Nominal : sale au 1er passage, propre au 2e
    final = run_pipeline(toy_agents(quality_residual_until_pass=1),
                         "data/raw/olist_orders.csv", domain="retail")
    show("SCÉNARIO 1 — nominal avec une relance qualité", final)
    (RUNS / "state.json").write_text(
        json.dumps(final, indent=2, ensure_ascii=False, default=to_json), encoding="utf-8")

    # 2. Boucle bornée : toujours sale
    final = run_pipeline(toy_agents(quality_residual_until_pass=99),
                         "data/raw/olist_orders.csv", domain="retail")
    show("SCÉNARIO 2 — boucle qualité qui atteint son plafond", final)

    # 3. Échec : l'agent ETL plante
    final = run_pipeline(toy_agents(quality_residual_until_pass=0, etl=failing_agent),
                         "data/raw/olist_orders.csv", domain="retail")
    show("SCÉNARIO 3 — échec de l'ETL, saut vers XAI", final)

    # Le graphe compilé, généré automatiquement par LangGraph
    mermaid = build_graph(toy_agents()).get_graph().draw_mermaid()
    (RUNS / "graph.mmd").write_text(mermaid, encoding="utf-8")
    print("\nFichiers produits : runs/graph.mmd (graphe)  runs/state.json (état final, scénario 1)")
