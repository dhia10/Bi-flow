"""
Unit & Integration tests for production LangGraph BI-Flow nodes.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
ORCH_DIR = ROOT_DIR / "Orchestrator"
if str(ORCH_DIR) not in sys.path:
    sys.path.insert(0, str(ORCH_DIR))

import pytest
from Orchestrator.agents.nodes import (
    analyst_node,
    dashboard_node,
    etl_node,
    get_production_agents,
    profiler_node,
    quality_node,
    semantic_node,
    xai_node,
)
from Orchestrator.core.state import initial_state
from Orchestrator.orchestrator.orchestrator import build_graph, run_pipeline


def test_production_nodes_registration():
    agents = get_production_agents()
    assert len(agents) == 7
    expected = {"profiler", "quality", "etl", "semantic", "analyst", "dashboard", "xai"}
    assert set(agents.keys()) == expected


def test_build_production_graph():
    agents = get_production_agents()
    graph = build_graph(agents)
    assert graph is not None


def test_full_pipeline_execution():
    test_csv = ROOT_DIR / "bi_pipeline" / "data" / "mock_clean_data.csv"
    agents = get_production_agents()
    state = run_pipeline(agents, dataset_ref=str(test_csv), domain="retail")

    assert state.get("run_id") is not None
    trace_nodes = [t.node for t in state.get("trace", [])]
    assert "profiler" in trace_nodes
    assert "quality" in trace_nodes
    assert "etl" in trace_nodes
    assert "semantic" in trace_nodes
    assert "analyst" in trace_nodes
    assert "dashboard" in trace_nodes
    assert "xai" in trace_nodes

    assert len(state.get("decision_log", [])) >= 7
    assert state.get("xai_report", {}).get("verdict") is not None
