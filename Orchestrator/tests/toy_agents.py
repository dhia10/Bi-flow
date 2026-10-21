"""
AGENTS-JOUETS — remplacent les vrais agents des coéquipiers pour tester
l'orchestrateur tout seul. Chacun respecte le contrat : (state) -> dict.

Remplacez-les un par un par les vrais agents, au fur et à mesure.
"""
from __future__ import annotations

from core.state import BIFlowState, DecisionRecord


def _toy(agent_name: str, **out):
    """Fabrique un agent-jouet qui écrit `out` dans l'état et journalise."""
    def agent(state: BIFlowState) -> dict:
        return {**out, "decision_log": [DecisionRecord(
            agent=agent_name, action="traitement simulé", rationale="agent-jouet")]}
    return agent


def toy_quality(residual_until_pass: int = 1):
    """Agent qualité simulé : signale des problèmes résiduels pendant les
    `residual_until_pass` premiers passages, puis déclare les données propres.
      0  -> propre dès le 1er passage (pas de boucle)
      1  -> sale au 1er passage, propre au 2e (une relance)
      99 -> toujours sale (la boucle atteint son plafond)
    """
    passes = {"n": 0}

    def agent(state: BIFlowState) -> dict:
        passes["n"] += 1
        residual = passes["n"] <= residual_until_pass
        return {
            "clean_data": "data/clean/orders.parquet",
            "quality_report": {"has_residual_issues": residual, "passage": passes["n"]},
            "decision_log": [DecisionRecord(
                agent="DataQuality",
                action=f"nettoyage (passage {passes['n']})",
                rationale="problèmes résiduels détectés" if residual else "données propres",
                evidence={"has_residual_issues": residual},
            )],
        }
    return agent


def failing_agent(state: BIFlowState) -> dict:
    """Agent qui plante, pour tester la gestion d'échec."""
    raise RuntimeError("connexion à la base impossible")


def toy_xai(state: BIFlowState) -> dict:
    """XAI simulé : relit la trace et le journal, résume le run."""
    ctrl = state["control"]
    return {
        "xai_report": {
            "verdict": "PARTIEL" if ctrl.aborted else "COMPLET",
            "noeuds_executes": [t.node for t in state["trace"]],
            "nb_decisions": len(state["decision_log"]),
            "passages_quality": ctrl.runs.get("quality", 0),
            "erreurs": ctrl.errors,
        },
        "decision_log": [DecisionRecord(agent="XAI", action="audit du run",
                                        rationale="relecture de trace et decision_log")],
    }


def toy_agents(quality_residual_until_pass: int = 1, **overrides) -> dict:
    """Dictionnaire complet d'agents-jouets ; `overrides` remplace n'importe lequel."""
    agents = {
        "profiler":  _toy("DataProfiler", profile_report={"rows": 99441, "has_issues": True}),
        "quality":   toy_quality(quality_residual_until_pass),
        "etl":       _toy("ETL", data_model={"fact": "fact_orders",
                                             "dims": ["dim_client", "dim_produit", "dim_date"]}),
        "semantic":  _toy("BISemantic", kpi_catalog={"CA": 1.2e6, "panier_moyen": 137.5}),
        "analyst":   _toy("BIAnalyst", insights=["Le CA progresse de 8 % au T3"]),
        "dashboard": _toy("DashboardGen", dashboard={"visuels": 6}),
        "xai":       toy_xai,
    }
    agents.update(overrides)
    return agents
