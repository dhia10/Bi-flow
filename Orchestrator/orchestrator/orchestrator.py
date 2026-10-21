"""
=============================================================================
 BI-Flow — AGENT ORCHESTRATEUR
=============================================================================

RÔLE
    L'orchestrateur ne traite AUCUNE donnée. Il décide :
      - QUI s'exécute,
      - DANS QUEL ORDRE,
      - QUOI FAIRE en cas de problème (relancer un agent, ou arrêter).

PRINCIPE (LangGraph)
    - Chaque agent est un NŒUD du graphe : une fonction  (state) -> dict.
    - Les agents ne se parlent jamais. Ils lisent et écrivent dans un ÉTAT
      PARTAGÉ (BIFlowState, défini dans core/state.py).
    - Les ARÊTES disent qui passe après qui :
        * arête fixe           : A -> B, toujours ;
        * arête conditionnelle : une fonction de routage lit l'état et
                                 renvoie le nom du prochain nœud.
    - Après chaque nœud, LangGraph fusionne la sortie de l'agent dans l'état,
      puis suit l'arête qui sort de ce nœud. Il répète jusqu'à END.

LE GRAPHE

    START -> profiler -> quality -> etl -> semantic -> analyst -> dashboard -> xai -> END
                          ^    |
                          |____|   boucle de re-nettoyage (au plus 2 relances)

    Si un agent échoue : saut direct vers xai, qui explique l'échec.

PLAN DU FICHIER
    1. Configuration   : noms des nœuds, plafond de la boucle
    2. Enveloppe       : _wrap() — compteur, chrono, erreurs, contrôle, trace
    3. Routage         : fonctions qui choisissent l'arête à suivre
    4. Construction    : build_graph() — les nœuds puis les arêtes
    5. Exécution       : run_pipeline()

LANCER LA DÉMO (depuis le dossier bi_flow/)
    python demo.py
    python -m pytest -v
"""
from __future__ import annotations

import copy
import logging
import time
from typing import Callable

from langgraph.graph import END, START, StateGraph

from core.state import (
    INPUT_KEYS,
    ORCHESTRATOR_KEYS,
    STATE_KEYS,
    BIFlowState,
    ControlSignals,
    DecisionRecord,
    TraceEvent,
    initial_state,
)

log = logging.getLogger("bi_flow.orchestrator")

# Un agent = une fonction qui reçoit l'état et renvoie SES ajouts (un dict).
Agent = Callable[[BIFlowState], dict]


# =========================================================================== #
# 1. CONFIGURATION                                                            #
# =========================================================================== #

# Ordre nominal des agents de traitement.
PIPELINE = ["profiler", "quality", "etl", "semantic", "analyst", "dashboard"]

# Nœud final : il s'exécute TOUJOURS, même après un échec, pour expliquer le run.
FINAL_NODE = "xai"

# Tous les agents que l'orchestrateur doit recevoir.
ALL_NODES = PIPELINE + [FINAL_NODE]

# Boucle de rétroaction : nombre maximal de RELANCES de l'agent qualité
# (donc au plus 1 passage normal + 2 relances = 3 passages). Jamais d'infini.
MAX_QUALITY_RETRIES = 2


# =========================================================================== #
# 2. ENVELOPPE — chaque agent passe par ici avant d'entrer dans le graphe.    #
# =========================================================================== #
# L'agent d'un coéquipier reste une simple fonction (state) -> dict.
# C'est l'enveloppe qui ajoute ce dont l'orchestrateur a besoin :
#   (a) compter les passages     -> control.runs   (utilisé par le routage)
#   (b) chronométrer l'agent     -> trace
#   (c) attraper ses erreurs     -> control.aborted (le pipeline ne plante pas)
#   (d) filtrer sa sortie        -> un agent ne peut pas écrire un champ réservé
#   (e) journaliser les décisions de l'orchestrateur -> decision_log (lu par XAI)

def _wrap(name: str, agent: Agent) -> Callable[[BIFlowState], dict]:

    def node(state: BIFlowState) -> dict:
        # (a) Compter ce passage. On travaille sur une COPIE : on ne modifie
        #     jamais l'état en place, on renvoie la nouvelle valeur.
        ctrl = copy.deepcopy(state.get("control") or ControlSignals())
        attempt = ctrl.runs.get(name, 0) + 1
        ctrl.runs[name] = attempt

        notes: list[DecisionRecord] = []        # décisions de l'orchestrateur
        warnings: list[str] = []

        if attempt > 1:                         # c'est une relance -> on le dit
            notes.append(DecisionRecord(
                agent="Orchestrator",
                action=f"relance de '{name}' (passage {attempt})",
                rationale="problèmes résiduels signalés par "
                          "quality_report.has_residual_issues",
                evidence={"relances_max": MAX_QUALITY_RETRIES},
            ))

        # (b) + (c) Exécuter l'agent, chronométré, sans jamais faire planter le graphe.
        t0 = time.perf_counter()
        try:
            update = agent(state) or {}
            if not isinstance(update, dict):
                raise TypeError(f"l'agent doit renvoyer un dict, reçu {type(update).__name__}")
            update = dict(update)

            # (d) Retirer les champs interdits ou inconnus de BIFlowState.
            for key in list(update):
                if key in INPUT_KEYS | ORCHESTRATOR_KEYS:
                    update.pop(key)
                    warnings.append(f"champ réservé ignoré : '{key}'")
                elif key not in STATE_KEYS:
                    update.pop(key)
                    warnings.append(f"champ inconnu ignoré : '{key}'")

            agent_log = update.get("decision_log") or []
            if isinstance(agent_log, DecisionRecord):
                agent_log = [agent_log]
            status, message = "success", "; ".join(warnings)

        except Exception as exc:                # échec de l'agent
            update, agent_log = {}, []
            status, message = "failed", f"{type(exc).__name__}: {exc}"
            ctrl.aborted = True
            ctrl.errors.append({"node": name, "error": message})
            notes.append(DecisionRecord(
                agent="Orchestrator",
                action=f"arrêt du pipeline après l'échec de '{name}' -> saut vers '{FINAL_NODE}'",
                rationale="les agents suivants dépendent de sa sortie",
                confidence=1.0,
                evidence={"erreur": message},
            ))

        duration = round(time.perf_counter() - t0, 4)
        for w in warnings:
            log.warning("[%s] %s", name, w)

        # (e) Boucle qualité épuisée : on continue malgré tout, mais on le trace.
        if (name == "quality" and status == "success"
                and _has_residual_issues({**state, **update})
                and attempt - 1 >= MAX_QUALITY_RETRIES):
            notes.append(DecisionRecord(
                agent="Orchestrator",
                action="poursuite vers 'etl' malgré des problèmes résiduels",
                rationale=f"plafond de {MAX_QUALITY_RETRIES} relances atteint",
                confidence=0.5,
                evidence={"passages_quality": attempt},
            ))

        # Ce que le nœud renvoie à LangGraph (qui le fusionne dans l'état).
        update["decision_log"] = notes + list(agent_log)   # ajouté au journal
        update["trace"] = [TraceEvent(name, status, attempt, duration, message)]
        update["control"] = ctrl
        return update

    node.__name__ = f"node_{name}"
    return node


# =========================================================================== #
# 3. ROUTAGE — après un nœud, quelle arête suivre ?                           #
# =========================================================================== #
# Une fonction de routage LIT l'état et RENVOIE le nom du prochain nœud.
# Elle ne modifie rien (dans LangGraph, un routeur ne peut pas écrire l'état).

def _aborted(state: BIFlowState) -> bool:
    ctrl = state.get("control")
    return bool(ctrl and ctrl.aborted)


def _has_residual_issues(state: BIFlowState) -> bool:
    return bool((state.get("quality_report") or {}).get("has_residual_issues"))


def go_to(next_node: str) -> Callable[[BIFlowState], str]:
    """Arête « normale » : vers `next_node`, SAUF si un agent a échoué -> xai."""
    def route(state: BIFlowState) -> str:
        return FINAL_NODE if _aborted(state) else next_node
    route.__name__ = f"go_to_{next_node}"
    return route


def route_after_quality(state: BIFlowState) -> str:
    """Boucle de rétroaction de l'agent qualité.

    - un agent a échoué                          -> xai
    - problèmes résiduels ET relances restantes  -> quality (on relance)
    - sinon                                      -> etl     (on avance)
    """
    if _aborted(state):
        return FINAL_NODE
    retries_done = state["control"].runs.get("quality", 0) - 1   # 1er passage ≠ relance
    if _has_residual_issues(state) and retries_done < MAX_QUALITY_RETRIES:
        return "quality"
    return "etl"


# =========================================================================== #
# 4. CONSTRUCTION DU GRAPHE = l'orchestrateur                                 #
# =========================================================================== #
# Les agents sont INJECTÉS via un dictionnaire {nom_du_noeud: fonction}.
# L'orchestrateur n'importe aucun agent : on peut remplacer un vrai agent
# par un agent-jouet sans toucher à ce fichier.

def build_graph(agents: dict[str, Agent]):
    missing = [n for n in ALL_NODES if n not in agents]
    if missing:
        raise ValueError(f"Agents manquants : {missing}")

    g = StateGraph(BIFlowState)

    # 4.1 — NŒUDS : un nœud par agent, chacun passé dans l'enveloppe.
    for name in ALL_NODES:
        g.add_node(name, _wrap(name, agents[name]))

    # 4.2 — ARÊTES : qui passe après qui.
    g.add_edge(START, "profiler")                                     # point d'entrée
    g.add_conditional_edges("profiler",  go_to("quality"),   ["quality", "xai"])
    g.add_conditional_edges("quality",   route_after_quality, ["quality", "etl", "xai"])
    g.add_conditional_edges("etl",       go_to("semantic"),  ["semantic", "xai"])
    g.add_conditional_edges("semantic",  go_to("analyst"),   ["analyst", "xai"])
    g.add_conditional_edges("analyst",   go_to("dashboard"), ["dashboard", "xai"])
    g.add_edge("dashboard", "xai")                                    # arête fixe
    g.add_edge("xai", END)                                            # fin du pipeline

    # 4.3 — COMPILATION : LangGraph vérifie le graphe et le rend exécutable.
    return g.compile()


# =========================================================================== #
# 5. EXÉCUTION                                                                #
# =========================================================================== #

def _recursion_limit() -> int:
    """Nombre maximal d'étapes : tous les nœuds + toutes les relances + marge."""
    return len(ALL_NODES) + MAX_QUALITY_RETRIES + 5


def run_pipeline(agents: dict[str, Agent], dataset_ref: str,
                 domain: str = "generic") -> BIFlowState:
    """Point d'entrée : construit le graphe et exécute le pipeline complet."""
    graph = build_graph(agents)
    return graph.invoke(initial_state(dataset_ref, domain),
                        {"recursion_limit": _recursion_limit()})
