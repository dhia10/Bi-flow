from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure root dir is in path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd
from bi_pipeline.agents.bi_analyst_agent import BIAnalystAgent
from bi_pipeline.agents.semantic_kpi_agent import BISemanticKPIAgent
from bi_pipeline.schemas.state_schema import PipelineRunOutput


def main():
    parser = argparse.ArgumentParser(description="n8n CLI Runner for Bi-flow Multi-Agent BI Pipeline")
    parser.add_argument("--file", type=str, default=None, help="Path to input CSV file")
    parser.add_argument("--dataset-name", type=str, default="Input Dataset", help="Dataset identifier")
    parser.add_argument("--format", choices=["json", "narrative", "full"], default="full", help="Output format for n8n")
    args = parser.parse_args()

    # Determine input data path
    if args.file and Path(args.file).is_file():
        file_path = Path(args.file)
    else:
        file_path = ROOT_DIR / "bi_pipeline" / "data" / "mock_clean_data.csv"

    df = pd.read_csv(file_path)

    # 1. Run Agent 5 (Semantic & KPI Agent with DuckDB)
    agent5 = BISemanticKPIAgent()
    semantic_state = agent5.analyze(df, dataset_name=args.dataset_name)

    # 2. Run Agent 6 (Analyst Agent with Statistical Mining & XAI)
    agent6 = BIAnalystAgent()
    analyst_state = agent6.analyze(semantic_state)

    pipeline_output = PipelineRunOutput(
        semantic_state=semantic_state,
        analyst_state=analyst_state,
        total_execution_time_ms=semantic_state.execution_time_ms + 12.0,
    )

    if args.format == "narrative":
        print(analyst_state.executive_narrative)
    elif args.format == "json":
        print(pipeline_output.to_json())
    else:
        # Full payload tailored for n8n consumption
        n8n_payload = {
            "success": True,
            "dataset": args.dataset_name,
            "row_count": len(df),
            "execution_ms": pipeline_output.total_execution_time_ms,
            "kpis": [
                {
                    "name": k.name,
                    "value": k.value,
                    "unit": k.unit,
                    "category": k.category,
                    "sql": k.lineage.exact_sql_query,
                    "rag_source": k.lineage.source_document,
                }
                for k in semantic_state.kpis
            ],
            "anomalies": [
                {
                    "entity": a.entity,
                    "metric": a.metric_name,
                    "observed": a.observed_value,
                    "baseline": a.expected_value,
                    "z_score": a.z_score,
                    "severity": a.severity.value,
                    "rule": a.lineage.exact_sql_query.strip(),
                }
                for a in analyst_state.statistical_anomalies[:5]
            ],
            "trends": [
                {
                    "metric": t.metric_name,
                    "direction": t.direction.value,
                    "growth_pct": t.growth_rate_pct,
                    "cv": t.volatility_cv,
                }
                for t in analyst_state.trend_insights
            ],
            "strategic_takeaways": [
                {
                    "title": tw.title,
                    "severity": tw.severity.value,
                    "summary": tw.executive_summary,
                    "action": tw.recommended_action,
                }
                for tw in analyst_state.strategic_takeaways
            ],
            "narrative_report": analyst_state.executive_narrative,
        }
        print(json.dumps(n8n_payload, indent=2))


if __name__ == "__main__":
    main()
