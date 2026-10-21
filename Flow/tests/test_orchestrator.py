"""
TESTS DE L'ORCHESTRATEUR — lancer depuis bi_flow/ :   python -m pytest -v

Chaque test vérifie UN comportement promis par l'orchestrateur.
"""
import pytest

from core.state import DecisionRecord
from orchestrator.orchestrator import build_graph, run_pipeline
from tests.toy_agents import failing_agent, toy_agents


def order(final):
    return [t.node for t in final["trace"]]


def test_ordre_nominal_sans_boucle():
    final = run_pipeline(toy_agents(quality_residual_until_pass=0), "x.csv")
    assert order(final) == ["profiler", "quality", "etl", "semantic",
                            "analyst", "dashboard", "xai"]
    assert final["xai_report"]["verdict"] == "COMPLET"


def test_boucle_qualite_une_relance():
    final = run_pipeline(toy_agents(quality_residual_until_pass=1), "x.csv")
    assert final["control"].runs["quality"] == 2
    assert order(final)[:4] == ["profiler", "quality", "quality", "etl"]


def test_boucle_bornee_jamais_infinie():
    final = run_pipeline(toy_agents(quality_residual_until_pass=99), "x.csv")
    assert final["control"].runs["quality"] == 3          # 1 passage + 2 relances
    assert "etl" in order(final)                          # on avance quand même
    assert any("plafond" in d.rationale for d in final["decision_log"])


def test_echec_saute_vers_xai():
    final = run_pipeline(toy_agents(quality_residual_until_pass=0, etl=failing_agent), "x.csv")
    assert order(final) == ["profiler", "quality", "etl", "xai"]
    assert final["control"].aborted is True
    assert final["control"].errors[0]["node"] == "etl"
    assert final["xai_report"]["verdict"] == "PARTIEL"


def test_un_agent_ne_peut_pas_ecrire_un_champ_reserve():
    def tricheur(state):
        return {"control": "piraté", "inconnu": 1,
                "decision_log": [DecisionRecord(agent="ETL", action="ok")]}
    final = run_pipeline(toy_agents(quality_residual_until_pass=0, etl=tricheur), "x.csv")
    etl_trace = next(t for t in final["trace"] if t.node == "etl")
    assert "champ réservé ignoré : 'control'" in etl_trace.message
    assert "champ inconnu ignoré : 'inconnu'" in etl_trace.message
    assert final["control"].aborted is False


def test_agent_manquant_refuse_a_la_construction():
    agents = toy_agents()
    del agents["analyst"]
    with pytest.raises(ValueError, match="analyst"):
        build_graph(agents)
