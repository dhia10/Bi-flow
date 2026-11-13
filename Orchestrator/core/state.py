"""
ÉTAT PARTAGÉ — BI-Flow.

Ce module ne dépend d'aucun agent ni de l'orchestrateur : agents ET
orchestrateur l'importent, ce qui évite toute importation circulaire.

  - DecisionRecord : une décision explicable (écrite par les agents)
  - TraceEvent     : une exécution de nœud (écrite par l'orchestrateur)
  - ControlSignals : signaux de contrôle (écrits par l'orchestrateur)
  - BIFlowState    : l'état LangGraph qui circule dans tout le pipeline
"""
from __future__ import annotations

import operator
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal, TypedDict


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class DecisionRecord:
    """Une décision explicable d'un agent — la matière première du XAI."""
    agent: str                                   # nom STABLE de l'agent
    action: str                                  # ce qui a été fait
    rationale: str = ""                          # POURQUOI
    confidence: float = 1.0                      # 0.0–1.0
    alternatives_considered: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_now)


@dataclass
class TraceEvent:
    """Une exécution d'un nœud, enregistrée par l'orchestrateur (pas par les agents)."""
    node: str
    status: Literal["success", "failed", "skipped"]
    attempt: int                                 # n-ième passage dans ce nœud
    duration_s: float
    message: str = ""
    timestamp: str = field(default_factory=_now)


@dataclass
class ControlSignals:
    """Signaux de contrôle — écrits UNIQUEMENT par l'orchestrateur."""
    runs: dict[str, int] = field(default_factory=dict)   # passages par nœud
    errors: list[dict[str, str]] = field(default_factory=list)
    aborted: bool = False                                 # un agent a échoué


class BIFlowState(TypedDict, total=False):
    # --- Entrée ---
    run_id: str
    dataset_ref: str             # chemin CSV / chaîne de connexion / URL d'API
    domain: str                  # "retail", "luxury", "banking", "telecom", ...
    business_context: str        # Contexte métier injecté via le formulaire
    few_shot_examples: list      # Exemples Few-Shot (In-Context Learning)

    # --- Sorties des agents (chaque agent écrit SES champs) ---
    profile_report: dict         # Data Profiler
    clean_data: Any              # Data Quality & Cleaning
    quality_report: dict         # Data Quality & Cleaning (dont "has_residual_issues")
    data_model: Any              # ETL
    kpi_catalog: dict            # BI Semantic & KPI
    insights: list               # BI Analyst
    dashboard: dict              # Dashboard Generator
    xai_report: dict             # XAI

    # --- Journaux : listes FUSIONNÉES (operator.add), jamais écrasées ---
    decision_log: Annotated[list[DecisionRecord], operator.add]
    trace: Annotated[list[TraceEvent], operator.add]

    # --- Contrôle (orchestrateur seulement) ---
    control: ControlSignals

    # --- Détection & Télémétrie JSON inter-agents ---
    agent_payloads: dict[str, Any]
    json_transitions: Annotated[list[dict[str, Any]], operator.add]


# Champs qu'un agent n'a pas le droit d'écrire
INPUT_KEYS = frozenset({"run_id", "dataset_ref", "domain", "business_context", "few_shot_examples"})
ORCHESTRATOR_KEYS = frozenset({"control", "trace", "agent_payloads", "json_transitions"})
STATE_KEYS = frozenset(BIFlowState.__annotations__)


def initial_state(
    dataset_ref: str,
    domain: str = "generic",
    business_context: str = "",
    few_shot_examples: list | None = None
) -> BIFlowState:
    return BIFlowState(
        run_id=uuid.uuid4().hex[:8],
        dataset_ref=dataset_ref,
        domain=domain,
        business_context=business_context,
        few_shot_examples=few_shot_examples or [],
        decision_log=[],
        trace=[],
        control=ControlSignals(),
        agent_payloads={},
        json_transitions=[],
    )
