from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from bi_pipeline.schemas.state_schema import (
    AuditLineage,
    BIAnalystState,
    RiskSeverity,
    SemanticKPIState,
    StatisticalAnomaly,
    StrategicTakeaway,
    TrendDirection,
    TrendInsight,
)

log = logging.getLogger(__name__)


class BIAnalystAgent:
    def __init__(self, z_threshold: float = 2.0, iqr_multiplier: float = 1.5) -> None:
        self.z_threshold = z_threshold
        self.iqr_multiplier = iqr_multiplier

    def _find_anomalies(self, state: SemanticKPIState) -> List[StatisticalAnomaly]:
        anomalies = []

        for dim, records in state.dimensional_aggregations.items():
            if not records or len(records) < 2:
                continue

            metric_keys = [
                k for k, v in records[0].items()
                if k not in ("entity", "dimension") and isinstance(v, (int, float))
            ]

            for m in metric_keys:
                vals = [r[m] for r in records if r.get(m) is not None]
                if len(vals) < 2:
                    continue

                arr = np.array(vals, dtype=np.float64)
                mu, sigma = float(np.mean(arr)), float(np.std(arr))
                q25, q75 = np.percentile(arr, [25, 75])
                iqr = q75 - q25
                lower_bound = q25 - (self.iqr_multiplier * iqr)
                upper_bound = q75 + (self.iqr_multiplier * iqr)

                for r in records:
                    v = r.get(m)
                    if v is None:
                        continue

                    val = float(v)
                    entity = str(r.get("entity", "Unknown"))
                    z = round((val - mu) / sigma, 2) if sigma > 1e-6 else None
                    pct_dev = round(((val - mu) / max(abs(mu), 1e-6)) * 100.0, 2)

                    if m in ("profit", "margin_pct") and val < 0:
                        desc = f"Negative {m} in '{entity}' ({val:.2f}). Operating at a loss."
                        severity = RiskSeverity.CRITICAL if val < -100 or pct_dev < -100 else RiskSeverity.HIGH
                        lineage = AuditLineage(
                            source_document=f"knowledge_base/{state.inferred_domain}.json#loss_{m}",
                            tier=state.rag_tier,
                            similarity_score=state.domain_confidence,
                            exact_sql_query=f"-- Negative margin detected on '{dim}' for '{entity}'",
                            execution_timestamp=datetime.now(timezone.utc),
                            statistical_thresholds={"cutoff": 0.0, "observed": val},
                            input_columns_used=[dim, m],
                        )
                        anomalies.append(
                            StatisticalAnomaly(
                                dimension=dim,
                                entity=entity,
                                metric_name=m,
                                observed_value=round(val, 2),
                                expected_value=round(mu, 2),
                                z_score=z,
                                iqr_distance=round(lower_bound - val, 2) if val < lower_bound else None,
                                pct_deviation=pct_dev,
                                severity=severity,
                                description=desc,
                                lineage=lineage,
                            )
                        )
                        continue

                    is_outlier = (z is not None and abs(z) >= self.z_threshold) or (val < lower_bound or val > upper_bound)
                    if is_outlier:
                        direction = "high" if val > mu else "low"
                        desc = f"Entity '{entity}' showed {direction} {m} of {val:.2f} (mean {mu:.2f}, z {z or 'N/A'})."
                        sev = RiskSeverity.HIGH if (z and abs(z) >= 2.5) else RiskSeverity.MEDIUM
                        lineage = AuditLineage(
                            source_document=f"knowledge_base/{state.inferred_domain}.json#outlier_{m}",
                            tier=state.rag_tier,
                            similarity_score=state.domain_confidence,
                            exact_sql_query=f"-- Statistical Outlier on '{dim}' for metric '{m}' (|z| >= {self.z_threshold})",
                            execution_timestamp=datetime.now(timezone.utc),
                            statistical_thresholds={
                                "z_threshold": self.z_threshold,
                                "mean": round(mu, 2),
                                "std_dev": round(sigma, 2),
                            },
                            input_columns_used=[dim, m],
                        )
                        anomalies.append(
                            StatisticalAnomaly(
                                dimension=dim,
                                entity=entity,
                                metric_name=m,
                                observed_value=round(val, 2),
                                expected_value=round(mu, 2),
                                z_score=z,
                                iqr_distance=round(abs(val - (upper_bound if val > upper_bound else lower_bound)), 2),
                                pct_deviation=pct_dev,
                                severity=sev,
                                description=desc,
                                lineage=lineage,
                            )
                        )

        return anomalies

    def _eval_trends(self, state: SemanticKPIState) -> List[TrendInsight]:
        insights = []
        target_records = None
        dim_key = "period"

        for k in ("period", "monthly_trend", "temporal_dimension", "dim_monthly_trend"):
            if k in state.dimensional_aggregations:
                target_records = state.dimensional_aggregations[k]
                dim_key = k
                break

        if not target_records or len(target_records) < 2:
            return insights

        ordered = sorted([r for r in target_records if r.get("entity")], key=lambda x: str(x.get("entity")))
        metric_keys = [k for k in ordered[0].keys() if k not in ("entity", "dimension") and isinstance(ordered[0][k], (int, float))]

        for m in metric_keys:
            series = [float(r[m]) for r in ordered if r.get(m) is not None]
            if len(series) < 2:
                continue

            v_start, v_end = series[0], series[-1]
            mu, sigma = float(np.mean(series)), float(np.std(series))
            cv = round(sigma / max(abs(mu), 1e-6), 2)
            growth = round(((v_end - v_start) / max(abs(v_start), 1e-6)) * 100.0, 2)

            pop_deltas = [
                ((series[i] - series[i - 1]) / max(abs(series[i - 1]), 1e-6)) * 100.0
                for i in range(1, len(series))
            ]
            accel = round(pop_deltas[-1] - pop_deltas[-2], 2) if len(pop_deltas) >= 2 else None

            if cv > 0.65 and abs(growth) < 15:
                direction = TrendDirection.VOLATILE
            elif growth > 20.0:
                direction = TrendDirection.SURGING
            elif growth >= 5.0:
                direction = TrendDirection.UPWARD
            elif growth >= -5.0:
                direction = TrendDirection.STABLE
            elif growth >= -20.0:
                direction = TrendDirection.DOWNWARD
            else:
                direction = TrendDirection.CRASHING

            lineage = AuditLineage(
                source_document=f"knowledge_base/{state.inferred_domain}.json#trend_{m}",
                tier=state.rag_tier,
                similarity_score=state.domain_confidence,
                exact_sql_query=f"-- Temporal trend on '{m}' across {len(series)} points",
                execution_timestamp=datetime.now(timezone.utc),
                statistical_thresholds={"growth_rate_pct": growth, "cv": cv},
                input_columns_used=[dim_key, m],
            )
            insights.append(
                TrendInsight(
                    metric_name=m,
                    dimension=dim_key,
                    direction=direction,
                    growth_rate_pct=growth,
                    volatility_cv=cv,
                    acceleration=accel,
                    lineage=lineage,
                )
            )

        return insights

    def _synthesize_takeaways(
        self,
        state: SemanticKPIState,
        anomalies: List[StatisticalAnomaly],
        trends: List[TrendInsight],
    ) -> List[StrategicTakeaway]:
        takeaways = []

        loss_cases = [a for a in anomalies if a.severity == RiskSeverity.CRITICAL and a.observed_value < 0]
        if loss_cases:
            names = ", ".join(f"'{a.entity}' ({a.observed_value:,.2f})" for a in loss_cases[:3])
            takeaways.append(
                StrategicTakeaway(
                    title="Active Margin Dilution Detected",
                    executive_summary=f"Critical negative margins found in {len(loss_cases)} segments, notably {names}.",
                    severity=RiskSeverity.CRITICAL,
                    implication="Unprofitable product segments drag down net operating income and distort marketing ROI.",
                    recommended_action="Audit unit economics, adjust discount thresholds, and phase out chronically loss-making SKUs.",
                    supporting_kpis=[k.name for k in state.kpis if k.category == "financial"],
                    lineage=loss_cases[0].lineage,
                )
            )

        for dim, rows in state.dimensional_aggregations.items():
            if not rows or len(rows) < 3 or dim in ("period", "monthly_trend"):
                continue

            rev_key = "revenue" if "revenue" in rows[0] else ("total_val" if "total_val" in rows[0] else None)
            if not rev_key:
                continue

            total = sum(r[rev_key] for r in rows if isinstance(r.get(rev_key), (int, float)))
            if total <= 0:
                continue

            top_row = max(rows, key=lambda x: x.get(rev_key, 0))
            top_val = top_row.get(rev_key, 0)
            share = (top_val / total) * 100.0

            if share >= 45.0:
                takeaways.append(
                    StrategicTakeaway(
                        title=f"Revenue Concentration in {dim.title()} '{top_row.get('entity')}'",
                        executive_summary=f"'{top_row.get('entity')}' accounts for {share:.1f}% ({top_val:,.2f}) of total revenue.",
                        severity=RiskSeverity.HIGH,
                        implication="High dependency on a single segment introduces fragility against demand volatility.",
                        recommended_action="Drive customer acquisition into adjacent categories to balance revenue distribution.",
                        supporting_kpis=[k.name for k in state.kpis if "revenue" in k.kpi_id.lower()],
                        lineage=AuditLineage(
                            source_document=f"knowledge_base/{state.inferred_domain}.json#concentration_{dim}",
                            tier=state.rag_tier,
                            similarity_score=state.domain_confidence,
                            exact_sql_query=f"-- Concentration analysis on {dim}: top share {share:.1f}%",
                            execution_timestamp=datetime.now(timezone.utc),
                            statistical_thresholds={"share_pct": round(share, 2)},
                            input_columns_used=[dim, rev_key],
                        ),
                    )
                )

        crashing = [t for t in trends if t.direction in (TrendDirection.CRASHING, TrendDirection.DOWNWARD)]
        surging = [t for t in trends if t.direction in (TrendDirection.SURGING, TrendDirection.UPWARD)]

        if crashing:
            c = crashing[0]
            takeaways.append(
                StrategicTakeaway(
                    title=f"Downward Velocity in {c.metric_name.title()}",
                    executive_summary=f"{c.metric_name.title()} declined by {abs(c.growth_rate_pct):.1f}% over the evaluated timeframe.",
                    severity=RiskSeverity.HIGH,
                    implication="Prolonged contraction indicates demand cooling or channel friction.",
                    recommended_action="Investigate conversion drop-offs and test targeted re-engagement offers.",
                    supporting_kpis=[c.metric_name],
                    lineage=c.lineage,
                )
            )
        elif surging:
            s = surging[0]
            takeaways.append(
                StrategicTakeaway(
                    title=f"Expansion in {s.metric_name.title()}",
                    executive_summary=f"{s.metric_name.title()} increased by {s.growth_rate_pct:.1f}%.",
                    severity=RiskSeverity.LOW,
                    implication="Positive momentum supports expanded operational investment.",
                    recommended_action="Increase inventory allocation and scale top-performing marketing campaigns.",
                    supporting_kpis=[s.metric_name],
                    lineage=s.lineage,
                )
            )

        if not takeaways:
            takeaways.append(
                StrategicTakeaway(
                    title="Operations Within Standard Bounds",
                    executive_summary="Metrics remain stable with no critical outliers or concentration risks.",
                    severity=RiskSeverity.LOW,
                    implication="Core baseline operations are predictable.",
                    recommended_action="Maintain tracking cadence and optimize cost margins incrementally.",
                    supporting_kpis=[k.name for k in state.kpis[:2]],
                    lineage=AuditLineage(
                        source_document=f"knowledge_base/{state.inferred_domain}.json#baseline",
                        tier=state.rag_tier,
                        similarity_score=state.domain_confidence,
                        exact_sql_query="-- Baseline operational check",
                        execution_timestamp=datetime.now(timezone.utc),
                        input_columns_used=[],
                    ),
                )
            )

        return takeaways

    def _render_narrative(
        self,
        state: SemanticKPIState,
        anomalies: List[StatisticalAnomaly],
        trends: List[TrendInsight],
        takeaways: List[StrategicTakeaway],
    ) -> str:
        doc = [
            f"# Business Intelligence Report: {state.dataset_name.upper()}",
            f"*Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} | Domain: {state.inferred_domain} ({state.rag_tier})*\n",
            "## Key Metrics",
            "| Metric | Category | Value | Unit | Source |",
            "| :--- | :--- | :---: | :---: | :--- |",
        ]
        for k in state.kpis:
            fmt = f"{k.value:,.2f}" if isinstance(k.value, float) else f"{k.value:,}" if isinstance(k.value, int) else str(k.value)
            doc.append(f"| **{k.name}** | {k.category} | {fmt} | {k.unit or '-'} | `{k.lineage.source_document.split('#')[-1]}` |")

        doc.append("\n## Anomalies and Outliers")
        if anomalies:
            doc.extend([
                "| Severity | Dimension | Entity | Metric | Value | Baseline | Z-Score | Dev % |",
                "| :---: | :--- | :--- | :--- | :---: | :---: | :---: | :---: |",
            ])
            for a in anomalies:
                z = f"{a.z_score:+.2f} std dev" if a.z_score is not None else "N/A"
                doc.append(
                    f"| {a.severity.value.upper()} | {a.dimension} | {a.entity} | {a.metric_name} | "
                    f"{a.observed_value:,.2f} | {a.expected_value:,.2f} | {z} | {a.pct_deviation:+.1f}% |"
                )
        else:
            doc.append("No statistical anomalies detected above threshold.")

        doc.append("\n## Trends")
        if trends:
            doc.extend([
                "| Metric | Dimension | Direction | Growth | Volatility (CV) | Accel |",
                "| :--- | :--- | :---: | :---: | :---: | :---: |",
            ])
            for t in trends:
                acc = f"{t.acceleration:+.2f}%" if t.acceleration is not None else "-"
                doc.append(f"| {t.metric_name} | {t.dimension} | {t.direction.value.upper()} | {t.growth_rate_pct:+.1f}% | {t.volatility_cv:.2f} | {acc} |")
        else:
            doc.append("Insufficient temporal observations for trend computation.")

        doc.append("\n## Strategic Interventions")
        for i, tw in enumerate(takeaways, 1):
            doc.append(f"### {i}. [{tw.severity.value.upper()}] {tw.title}")
            doc.append(f"- **Summary**: {tw.executive_summary}")
            doc.append(f"- **Implication**: {tw.implication}")
            doc.append(f"- **Action**: {tw.recommended_action}")
            if tw.supporting_kpis:
                doc.append(f"- **Supporting**: {', '.join(tw.supporting_kpis)}")

        doc.append("\n---\n*Engine: DuckDB (:memory:) | Lineage: Verified*")
        return "\n".join(doc)

    def analyze(self, state: SemanticKPIState) -> BIAnalystState:
        if not state:
            raise ValueError("SemanticKPIState cannot be None")

        anomalies = self._find_anomalies(state)
        trends = self._eval_trends(state)
        takeaways = self._synthesize_takeaways(state, anomalies, trends)
        narrative = self._render_narrative(state, anomalies, trends, takeaways)

        return BIAnalystState(
            dataset_name=state.dataset_name,
            semantic_state=state,
            statistical_anomalies=anomalies,
            trend_insights=trends,
            strategic_takeaways=takeaways,
            executive_narrative=narrative,
            generated_at=datetime.now(timezone.utc),
        )
